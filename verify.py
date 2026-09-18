"""
verify.py
---------
Prüft, ob eine CAD-Kontur (DXF) vollständig vom G-Code gefräst wird.

Ansatz:
- Alle Punkte der DXF-Kontur werden einzeln geprüft.
- Für jeden Punkt wird der Abstand zum nächsten G-Code-Punkt berechnet.
- Ist der Abstand ≤ Toleranz, gilt der Punkt als "gefräst".
- Sonst gilt er als "nicht gefräst" und wird rot markiert.

Ergebnis:
- Verifikationsbericht mit
  * Gesamtzahl Punkte
  * Anzahl OK / NICHT OK
  * Maximaler und mittlerer Abstand
  * Liste der fehlenden Segmente
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from gcode_parser import Motion, MotionType, ParseResult
from dxf_loader import Contour as DxfContour, Hole as DxfHole, DxfContent


# --------------------------------------------------------------------------- #
# Datenklassen
# --------------------------------------------------------------------------- #

@dataclass
class PointCheck:
    """Ergebnis einer einzelnen Punktprüfung."""
    point: Tuple[float, float]       # Sollpunkt (x, y)
    distance: float                  # Abstand zum nächsten G-Code-Punkt
    ok: bool                         # innerhalb Toleranz?
    closest_gcode_point: Tuple[float, float]


@dataclass
class ContourCheck:
    """Ergebnis der Prüfung einer DXF-Kontur."""
    contour_index: int               # Nummer der Kontur
    kind: str                        # "outer" | "inner" | "hole"
    layer: str                       # DXF-Layer-Name
    points_checked: int
    points_ok: int
    points_fail: int
    max_distance: float
    mean_distance: float
    point_checks: List[PointCheck] = field(default_factory=list)

    @property
    def tolerance_ok(self) -> bool:
        return self.points_fail == 0


@dataclass
class VerificationResult:
    """Gesamtergebnis der Verifikation."""
    contour_checks: List[ContourCheck] = field(default_factory=list)
    tolerance: float = 0.01
    total_points: int = 0
    total_ok: int = 0
    total_fail: int = 0
    max_distance_overall: float = 0.0
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Toleranz           : ±{self.tolerance:.3f} mm",
            f"Geprüfte Punkte    : {self.total_points}",
            f"  OK               : {self.total_ok}",
            f"  NICHT OK         : {self.total_fail}",
            f"Max. Abweichung    : {self.max_distance_overall:.4f} mm",
            f"Konturen geprüft   : {len(self.contour_checks)}",
        ]
        return "\n".join(lines)

    def failing_contours(self) -> List[ContourCheck]:
        return [c for c in self.contour_checks if not c.tolerance_ok]


# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #

@dataclass
class VerifyConfig:
    """Parameter für die Verifikation."""
    tolerance: float = 0.01          # Toleranz in mm
    hole_diameter_extra: float = 0.5  # zusätzliche Toleranz für Bohrungen (mm)


# --------------------------------------------------------------------------- #
# Punktewolke aus G-Code extrahieren
# --------------------------------------------------------------------------- #

def extract_gcode_points(
    parse_result: ParseResult,
    arc_resolution: float = 0.05,
) -> np.ndarray:
    """
    Sammelt alle Punkte aus G-Code-Bewegungen als Punktwolke.

    Pro Bewegung werden Zwischenpunkte eingefügt, damit auch
    Kreissehnen und lange Linien sauber erfasst werden.

    Rückgabe: numpy-Array (N, 2) mit XY-Punkten.
    """
    points: List[Tuple[float, float]] = []

    for m in parse_result.motions:
        if not m.is_cutting():
            continue

        start = (m.start[0], m.start[1])
        end = (m.end[0], m.end[1])

        if m.motion_type == MotionType.LINEAR:
            # Zwischenpunkte für glatte Abdeckung
            d = math.hypot(end[0] - start[0], end[1] - start[1])
            n = max(1, int(math.ceil(d / arc_resolution)))
            for t in np.linspace(0, 1, n + 1):
                x = start[0] + t * (end[0] - start[0])
                y = start[1] + t * (end[1] - start[1])
                points.append((float(x), float(y)))

        elif m.motion_type in (MotionType.ARC_CW, MotionType.ARC_CCW):
            arc_pts = _discretize_arc(m, arc_resolution)
            points.extend(arc_pts)

        else:
            points.append(start)
            points.append(end)

    if not points:
        return np.empty((0, 2), dtype=float)

    return np.array(points, dtype=float)


def _discretize_arc(motion: Motion,
                    resolution: float) -> List[Tuple[float, float]]:
    """Zerlegt einen Kreisbogen in eine Punktfolge."""
    if motion.arc_center is None or motion.arc_radius is None:
        return [(motion.start[0], motion.start[1]),
                (motion.end[0], motion.end[1])]

    cx, cy, _ = motion.arc_center
    r = motion.arc_radius
    sx, sy, _ = motion.start
    ex, ey, _ = motion.end

    start_angle = math.atan2(sy - cy, sx - cx)
    end_angle = math.atan2(ey - cy, ex - cx)

    if motion.motion_type == MotionType.ARC_CCW:
        if end_angle <= start_angle:
            end_angle += 2 * math.pi
        delta = end_angle - start_angle
    else:
        if end_angle >= start_angle:
            end_angle -= 2 * math.pi
        delta = start_angle - end_angle

    arc_length = abs(delta) * r
    n = max(3, int(math.ceil(arc_length / resolution)))
    angles = np.linspace(start_angle, start_angle + delta, n)
    xs = cx + r * np.cos(angles)
    ys = cy + r * np.sin(angles)
    return list(zip(xs.tolist(), ys.tolist()))


# --------------------------------------------------------------------------- #
# DXF-Konturen zu Punktfolgen konvertieren
# --------------------------------------------------------------------------- #

def dxf_contour_to_points(
    dxf_contour: DxfContour,
    arc_resolution: float = 0.05,
) -> np.ndarray:
    """
    Wandelt eine DXF-Kontur in eine dichte Punktfolge um.

    Die Kontur ist bereits eine Liste von XY-Punkten – wir interpolieren
    nur zusätzliche Zwischenpunkte, damit auch lange Geraden sauber
    geprüft werden.
    """
    pts = np.asarray(dxf_contour.points, dtype=float)
    if len(pts) < 2:
        return pts

    result: List[Tuple[float, float]] = []
    for i in range(len(pts) - 1):
        p0, p1 = pts[i], pts[i + 1]
        d = float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
        n = max(1, int(math.ceil(d / arc_resolution)))
        for t in np.linspace(0, 1, n, endpoint=False):
            result.append((
                p0[0] + t * (p1[0] - p0[0]),
                p0[1] + t * (p1[1] - p0[1]),
            ))
    result.append((float(pts[-1][0]), float(pts[-1][1])))
    return np.array(result, dtype=float)


def dxf_hole_to_points(
    hole: DxfHole,
    arc_resolution: float = 0.05,
) -> np.ndarray:
    """Wandelt eine DXF-Bohrung in einen Kreis aus Punkten um."""
    r = hole.diameter / 2.0
    if r <= 0:
        return np.array([[hole.x, hole.y]], dtype=float)

    n = max(16, int(math.ceil(2 * math.pi * r / arc_resolution)))
    angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
    xs = hole.x + r * np.cos(angles)
    ys = hole.y + r * np.sin(angles)
    return np.column_stack([xs, ys])


# --------------------------------------------------------------------------- #
# Punktprüfung
# --------------------------------------------------------------------------- #

def check_point_against_cloud(
    point: Tuple[float, float],
    cloud: np.ndarray,
) -> Tuple[float, Tuple[float, float]]:
    """
    Findet den nächsten G-Code-Punkt zu einem Sollpunkt.

    Rückgabe: (Abstand, nächster Punkt)
    """
    if cloud.size == 0:
        return float("inf"), (0.0, 0.0)

    dx = cloud[:, 0] - point[0]
    dy = cloud[:, 1] - point[1]
    dist_sq = dx * dx + dy * dy
    idx = int(np.argmin(dist_sq))
    return float(math.sqrt(dist_sq[idx])), (float(cloud[idx, 0]),
                                            float(cloud[idx, 1]))


# --------------------------------------------------------------------------- #
# Hauptfunktion
# --------------------------------------------------------------------------- #

def verify_dxf_against_gcode(
    dxf_content: DxfContent,
    parse_result: ParseResult,
    config: Optional[VerifyConfig] = None,
) -> VerificationResult:
    """
    Prüft, ob alle DXF-Konturen vom G-Code gefräst werden.

    Parameter:
        dxf_content   – DXF-Inhalt mit Konturen und Bohrungen
        parse_result  – G-Code-Parse-Ergebnis
        config        – VerifyConfig
    """
    config = config or VerifyConfig()
    result = VerificationResult(tolerance=config.tolerance)

    # 1) G-Code-Punktwolke extrahieren
    cloud = extract_gcode_points(parse_result)
    if cloud.size == 0:
        result.warnings.append(
            "Keine schneidenden Bewegungen im G-Code gefunden.")
        return result

    # 2) Alle DXF-Elemente prüfen
    contour_index = 0

    # ---- Äußere und innere Konturen ----
    for dxf_contour in dxf_content.contours:
        contour_index += 1
        pts = dxf_contour_to_points(dxf_contour)
        kind = _classify_contour(dxf_contour, dxf_content)

        check = _check_contour(
            contour_index, kind, dxf_contour.layer, pts, cloud,
            config.tolerance)
        result.contour_checks.append(check)

    # ---- Bohrungen ----
    for hole in dxf_content.holes:
        contour_index += 1
        pts = dxf_hole_to_points(hole)

        # Toleranz für Bohrungen etwas größer (Rundungsfehler)
        tol = config.tolerance + config.hole_diameter_extra * 0.5

        check = _check_contour(
            contour_index, "hole", hole.layer, pts, cloud, tol)
        result.contour_checks.append(check)

    # 3) Gesamtsumme
    for check in result.contour_checks:
        result.total_points += check.points_checked
        result.total_ok += check.points_ok
        result.total_fail += check.points_fail
        result.max_distance_overall = max(
            result.max_distance_overall, check.max_distance)

    return result


def _check_contour(
    contour_index: int,
    kind: str,
    layer: str,
    points: np.ndarray,
    cloud: np.ndarray,
    tolerance: float,
) -> ContourCheck:
    """Prüft eine einzelne Kontur gegen die G-Code-Punktwolke."""
    checks: List[PointCheck] = []
    ok_count = 0
    fail_count = 0
    max_dist = 0.0
    sum_dist = 0.0

    for p in points:
        pt = (float(p[0]), float(p[1]))
        dist, closest = check_point_against_cloud(pt, cloud)
        ok = dist <= tolerance
        checks.append(PointCheck(
            point=pt, distance=dist, ok=ok,
            closest_gcode_point=closest))
        if ok:
            ok_count += 1
        else:
            fail_count += 1
        max_dist = max(max_dist, dist)
        sum_dist += dist

    mean_dist = sum_dist / len(points) if len(points) > 0 else 0.0

    return ContourCheck(
        contour_index=contour_index,
        kind=kind,
        layer=layer,
        points_checked=len(points),
        points_ok=ok_count,
        points_fail=fail_count,
        max_distance=max_dist,
        mean_distance=mean_dist,
        point_checks=checks,
    )


def _classify_contour(dxf_contour: DxfContour,
                      dxf_content: DxfContent) -> str:
    """
    Klassifiziert eine Kontur als 'outer' oder 'inner'.

    Heuristik: Die Kontur mit der größten Bounding-Box ist 'outer',
    alle anderen sind 'inner'.
    """
    def bbox_area(c: DxfContour) -> float:
        x0, y0, x1, y1 = c.bbox
        return (x1 - x0) * (y1 - y0)

    if not dxf_content.contours:
        return "inner"

    areas = [bbox_area(c) for c in dxf_content.contours]
    if not areas:
        return "inner"
    max_area = max(areas)
    if bbox_area(dxf_contour) >= max_area - 1e-6:
        return "outer"
    return "inner"