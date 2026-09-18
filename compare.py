"""
compare.py
----------
Kern-Verifikation: Vergleicht DXF-Sollkonturen mit G-Code-Ist-Bewegungen.

Ansatz:
- DXF liefert Soll-Punkte (Konturen + Bohrungen)
- G-Code liefert Ist-Punktwolke (aus Schnittbewegungen)
- Für jeden Sollpunkt wird der nächste Ist-Punkt gesucht
- Abstand > Toleranz → Fehler

Performance:
- scipy.spatial.cKDTree für Nächster-Punkt-Suche (10-100x schneller)
- Fallback auf numpy, falls scipy fehlt
"""


from __future__ import annotations

import math
import os
from pathlib import Path

os.chdir(Path(__file__).parent)
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from gcode_parser import Motion, MotionType, ParseResult
from dxf_loader import Contour as DxfContour, Hole as DxfHole, DxfContent

try:
    from scipy.spatial import cKDTree
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# --------------------------------------------------------------------------- #
# Datenklassen
# --------------------------------------------------------------------------- #

@dataclass
class PointResult:
    """Prüfergebnis eines einzelnen Sollpunkts."""
    point: Tuple[float, float]
    distance: float
    ok: bool
    closest_gcode: Tuple[float, float]


@dataclass
class ElementResult:
    """Prüfergebnis eines DXF-Elements (Kontur oder Bohrung)."""
    index: int                        # fortlaufende Nummer
    kind: str                         # "contour" | "hole" | "outer" | "inner"
    label: str                        # Anzeigename (z.B. "Ø10 @ LKR 760")
    diameter: Optional[float] = None  # bei Bohrungen
    lkr: Optional[float] = None       # Lochkreis-Durchmesser bei Bohrungen
    points_checked: int = 0
    points_ok: int = 0
    points_fail: int = 0
    max_distance: float = 0.0
    mean_distance: float = 0.0
    failing_points: List[PointResult] = field(default_factory=list)
    tolerance: float = 0.01

    @property
    def ok(self) -> bool:
        return self.points_fail == 0

    @property
    def status(self) -> str:
        if self.ok:
            return "OK"
        if self.points_fail < self.points_checked * 0.05:
            return "KLEIN"
        return "FEHLER"


@dataclass
class GroupResult:
    """Gruppiertes Ergebnis (z. B. alle Ø10 auf LKR 760)."""
    label: str
    elements: List[ElementResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.elements)

    @property
    def ok_count(self) -> int:
        return sum(1 for e in self.elements if e.ok)

    @property
    def fail_count(self) -> int:
        return self.total - self.ok_count

    @property
    def worst_distance(self) -> float:
        return max((e.max_distance for e in self.elements), default=0.0)


@dataclass
class VerificationResult:
    """Gesamtergebnis der Verifikation."""
    tolerance: float = 0.01
    contour_results: List[ElementResult] = field(default_factory=list)
    hole_results: List[ElementResult] = field(default_factory=list)
    contour_groups: List[GroupResult] = field(default_factory=list)
    hole_groups: List[GroupResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # ---- Zusammenfassungen ----
    @property
    def total_elements(self) -> int:
        return len(self.contour_results) + len(self.hole_results)

    @property
    def total_ok(self) -> int:
        return sum(1 for e in self.contour_results + self.hole_results if e.ok)

    @property
    def total_fail(self) -> int:
        return self.total_elements - self.total_ok

    @property
    def max_distance_overall(self) -> float:
        all_e = self.contour_results + self.hole_results
        return max((e.max_distance for e in all_e), default=0.0)

    @property
    def total_points(self) -> int:
        all_e = self.contour_results + self.hole_results
        return sum(e.points_checked for e in all_e)

    def summary(self) -> str:
        return (
            f"Toleranz         : ±{self.tolerance:.3f} mm\n"
            f"Elemente         : {self.total_elements}\n"
            f"  OK             : {self.total_ok}\n"
            f"  FEHLER         : {self.total_fail}\n"
            f"Geprüfte Punkte  : {self.total_points}\n"
            f"Max. Abweichung  : {self.max_distance_overall:.4f} mm"
        )


# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #

@dataclass
class CompareConfig:
    tolerance: float = 0.01              # Toleranz in mm
    arc_resolution: float = 0.05         # Punktdichte für Bögen
    hole_diameter_extra: float = 0.1     # Zusatz-Toleranz für Bohrungen
    hole_min_diameter: float = 1.0       # Kreise < X mm ignorieren
    hole_max_diameter: float = 200.0     # Kreise > X mm sind Konturen, keine Bohrungen
    progress_callback: Optional[Callable[[int, int], None]] = None


# --------------------------------------------------------------------------- #
# Punktwolke (G-Code)
# --------------------------------------------------------------------------- #

class GcodePointCloud:
    """Kapselt die G-Code-Punktwolke für schnelle Abfragen."""

    def __init__(self, points: np.ndarray) -> None:
        self.points = points
        self.tree = None
        if HAS_SCIPY and len(points) > 0:
            self.tree = cKDTree(points)

    @classmethod
    def from_parse_result(cls,
                          parse_result: ParseResult,
                          arc_resolution: float = 0.05) -> "GcodePointCloud":
        points: List[Tuple[float, float]] = []

        for m in parse_result.motions:
            if not m.is_cutting():
                continue

            if m.motion_type == MotionType.LINEAR:
                start = (m.start[0], m.start[1])
                end = (m.end[0], m.end[1])
                d = math.hypot(end[0] - start[0], end[1] - start[1])
                n = max(1, int(math.ceil(d / arc_resolution)))
                for t in np.linspace(0, 1, n + 1):
                    points.append((start[0] + t * (end[0] - start[0]),
                                   start[1] + t * (end[1] - start[1])))
            elif m.motion_type in (MotionType.ARC_CW, MotionType.ARC_CCW):
                pts = _discretize_arc(m, arc_resolution)
                points.extend(pts)
            else:
                points.append((m.start[0], m.start[1]))
                points.append((m.end[0], m.end[1]))

        arr = np.array(points, dtype=float) if points else np.empty((0, 2))
        return cls(arr)

    def nearest(self, pt: Tuple[float, float]) -> Tuple[float, Tuple[float, float]]:
        """Findet den nächsten Punkt und gibt (Abstand, Punkt) zurück."""
        if self.points.size == 0:
            return float("inf"), (0.0, 0.0)

        if self.tree is not None:
            dist, idx = self.tree.query(pt)
            p = self.points[idx]
            return float(dist), (float(p[0]), float(p[1]))

        # numpy-Fallback
        dx = self.points[:, 0] - pt[0]
        dy = self.points[:, 1] - pt[1]
        dist_sq = dx * dx + dy * dy
        idx = int(np.argmin(dist_sq))
        return float(math.sqrt(dist_sq[idx])), (
            float(self.points[idx, 0]), float(self.points[idx, 1]))


def _discretize_arc(motion: Motion, resolution: float
                    ) -> List[Tuple[float, float]]:
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
# DXF-Punkte aufbereiten
# --------------------------------------------------------------------------- #

def dxf_contour_to_points(contour: DxfContour,
                          arc_resolution: float = 0.05) -> np.ndarray:
    """Wandelt eine DXF-Kontur in eine dichte Punktfolge um."""
    pts = np.asarray(contour.points, dtype=float)
    if len(pts) < 2:
        return pts

    result: List[Tuple[float, float]] = []
    for i in range(len(pts) - 1):
        p0, p1 = pts[i], pts[i + 1]
        d = float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
        n = max(1, int(math.ceil(d / arc_resolution)))
        for t in np.linspace(0, 1, n, endpoint=False):
            result.append((p0[0] + t * (p1[0] - p0[0]),
                           p0[1] + t * (p1[1] - p0[1])))
    result.append((float(pts[-1][0]), float(pts[-1][1])))
    return np.array(result, dtype=float)


def dxf_hole_to_points(hole: DxfHole,
                       arc_resolution: float = 0.05) -> np.ndarray:
    """Wandelt eine DXF-Bohrung in einen Kreis aus Punkten um."""
    r = hole.diameter / 2.0
    if r <= 0:
        return np.array([[hole.x, hole.y]], dtype=float)
    n = max(16, int(math.ceil(2 * math.pi * r / arc_resolution)))
    angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.column_stack([
        hole.x + r * np.cos(angles),
        hole.y + r * np.sin(angles),
    ])


# --------------------------------------------------------------------------- #
# Einzelprüfung
# --------------------------------------------------------------------------- #

def _check_points(points: np.ndarray,
                  cloud: GcodePointCloud,
                  tolerance: float) -> ElementResult:
    """Prüft eine Punktfolge gegen die G-Code-Punktwolke."""
    result = ElementResult(index=0, kind="?", label="", tolerance=tolerance)

    n = len(points)
    if n == 0:
        return result

    sum_dist = 0.0
    max_dist = 0.0
    ok_count = 0
    fail_count = 0
    failing: List[PointResult] = []

    for p in points:
        pt = (float(p[0]), float(p[1]))
        dist, closest = cloud.nearest(pt)
        ok = dist <= tolerance

        pr = PointResult(point=pt, distance=dist, ok=ok,
                         closest_gcode=closest)
        if ok:
            ok_count += 1
        else:
            fail_count += 1
            failing.append(pr)

        sum_dist += dist
        if dist > max_dist:
            max_dist = dist

    result.points_checked = n
    result.points_ok = ok_count
    result.points_fail = fail_count
    result.max_distance = max_dist
    result.mean_distance = sum_dist / n
    result.failing_points = failing
    return result


# --------------------------------------------------------------------------- #
# Hauptfunktion
# --------------------------------------------------------------------------- #

def verify(
    dxf_content: DxfContent,
    parse_result: ParseResult,
    config: Optional[CompareConfig] = None,
) -> VerificationResult:
    """
    Führt die Verifikation durch.

    Parameter:
        dxf_content    – DXF-Inhalt (Konturen + Bohrungen)
        parse_result   – G-Code-Parse-Ergebnis
        config         – CompareConfig
    """
    config = config or CompareConfig()
    result = VerificationResult(tolerance=config.tolerance)

    # 1) G-Code-Punktwolke bauen
    print("[compare] Baue G-Code-Punktwolke …")
    cloud = GcodePointCloud.from_parse_result(
        parse_result, config.arc_resolution)
    print(f"[compare]   {len(cloud.points)} Punkte aus G-Code")

    if len(cloud.points) == 0:
        result.warnings.append("Keine schneidenden G-Code-Bewegungen.")
        return result

    # 2) Konturen prüfen
    print("[compare] Prüfe Konturen …")
    n_contours = len(dxf_content.contours)
    for i, contour in enumerate(dxf_content.contours, 1):
        if config.progress_callback and i % 10 == 0:
            config.progress_callback(i, n_contours)
        pts = dxf_contour_to_points(contour, config.arc_resolution)
        er = _check_points(pts, cloud, config.tolerance)
        er.index = i
        er.kind = "contour"
        er.label = f"Kontur {i} (Layer {contour.layer})"
        result.contour_results.append(er)

    # 3) Bohrungen prüfen (mit Filter)
    print("[compare] Prüfe Bohrungen …")
    hole_idx = 0
    for hole in dxf_content.holes:
        # Filter: zu groß = Kontur, zu klein = Symbol
        if hole.diameter < config.hole_min_diameter:
            continue
        if hole.diameter > config.hole_max_diameter:
            continue

        hole_idx += 1
        pts = dxf_hole_to_points(hole, config.arc_resolution)

        lkr_r = math.hypot(hole.x, hole.y)
        lkr_d = lkr_r * 2
        tol = config.tolerance + config.hole_diameter_extra * 0.5

        er = _check_points(pts, cloud, tol)
        er.index = hole_idx
        er.kind = "hole"
        er.diameter = hole.diameter
        er.lkr = lkr_d if lkr_d > 0 else None
        if lkr_d > 0:
            er.label = f"Ø{hole.diameter:.2f} @ LKR {lkr_d:.1f}"
        else:
            er.label = f"Ø{hole.diameter:.2f} @ zentral"
        result.hole_results.append(er)

    # 4) Gruppierungen bilden
    result.contour_groups = _group_contours(result.contour_results)
    result.hole_groups = _group_holes(result.hole_results)

    return result


# --------------------------------------------------------------------------- #
# Gruppierung
# --------------------------------------------------------------------------- #

def _group_contours(elements: List[ElementResult]) -> List[GroupResult]:
    """Gruppiert Konturen nach Layer."""
    groups: Dict[str, List[ElementResult]] = {}
    for e in elements:
        key = e.label.split("(Layer ")[-1].rstrip(")") if "Layer" in e.label else "sonstige"
        groups.setdefault(key, []).append(e)

    return [
        GroupResult(label=f"Layer: {k}", elements=v)
        for k, v in sorted(groups.items())
    ]


def _group_holes(elements: List[ElementResult]) -> List[GroupResult]:
    """Gruppiert Bohrungen nach (Durchmesser, LKR)."""
    groups: Dict[str, List[ElementResult]] = {}
    for e in elements:
        d = round(e.diameter, 1) if e.diameter else 0
        lkr = round(e.lkr, 0) if e.lkr else 0
        key = f"Ø{d:.1f} @ LKR {lkr:.0f}"
        groups.setdefault(key, []).append(e)

    return [
        GroupResult(label=k, elements=v)
        for k, v in sorted(groups.items())
    ]