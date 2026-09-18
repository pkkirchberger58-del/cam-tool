"""
path_builder.py
---------------
Baut aus den G-Code-Bewegungen die fertige Endkontur(en).

Erkennt:
- Beliebige Anzahl von Konturen (offen oder geschlossen)
- Zustellungen mit Zusammenfassung auf tiefste Z-Ebene
- Bohrungen (CYCLE81 und G1-Einzelbewegungen)
- Radiusrückrechnung (nur bei aktivem G41/G42)

Ergebnis:
- Liste von Contour-Objekten (theoretisch)
- Liste von Contour-Objekten (tatsächlich, wenn Korrektur aktiv)
- Liste von Hole-Objekten (Bohrungen)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from gcode_parser import (
    Motion, MotionType, CutterComp, Plane, ParseResult
)


# --------------------------------------------------------------------------- #
# Datenklassen
# --------------------------------------------------------------------------- #

@dataclass
class Contour:
    """Eine zusammenhängende Kontur."""
    points: np.ndarray                  # (N, 2) XY-Punkte in mm
    z: float                            # Z-Tiefe (tiefste Stelle)
    tool: int                           # Werkzeugnummer
    closed: bool                        # geschlossen oder offen
    cutter_comp: CutterComp
    length: float                       # Länge in mm
    source_lines: List[int] = field(default_factory=list)

    def bbox(self) -> Tuple[float, float, float, float]:
        if len(self.points) == 0:
            return (0.0, 0.0, 0.0, 0.0)
        xs, ys = self.points[:, 0], self.points[:, 1]
        return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())

    def __repr__(self) -> str:
        x0, y0, x1, y1 = self.bbox()
        return (f"Contour(N={len(self.points)}, Z={self.z:.3f}, T{self.tool}, "
                f"{'closed' if self.closed else 'open'}, "
                f"bbox=({x0:.2f},{y0:.2f})-({x1:.2f},{y1:.2f}))")


@dataclass
class Hole:
    """Eine Bohrung (erkannt aus CYCLE81 oder isolierten G1-Z-Bewegungen)."""
    x: float
    y: float
    z_top: float                        # Oberkante
    z_bottom: float                     # Bohrtiefe
    tool: int
    diameter: float = 0.0               # aus Werkzeugdurchmesser
    source_line: int = 0

    @property
    def depth(self) -> float:
        return abs(self.z_bottom - self.z_top)

    def __repr__(self) -> str:
        return (f"Hole(x={self.x:.2f}, y={self.y:.2f}, "
                f"Ø{self.diameter:.1f}, T{self.tool}, "
                f"Tiefe={self.depth:.2f})")


@dataclass
class PathBuildResult:
    """Ergebnis der Kontur-Berechnung."""
    theoretical: List[Contour] = field(default_factory=list)
    actual: List[Contour] = field(default_factory=list)
    holes: List[Hole] = field(default_factory=list)
    by_tool: Dict[int, List[Contour]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Konturen (theoretisch) : {len(self.theoretical)}",
            f"Konturen (tatsächlich) : {len(self.actual)}",
            f"Bohrungen              : {len(self.holes)}",
            f"Werkzeuge              : {sorted(self.by_tool.keys())}",
        ]
        for tool, contours in sorted(self.by_tool.items()):
            zs = sorted({round(c.z, 3) for c in contours})
            lines.append(
                f"  T{tool:>2}: {len(contours):>3} Konturen, "
                f"Z-Ebenen: {zs[:5]}{' …' if len(zs) > 5 else ''}")
        if self.warnings:
            lines.append(f"Warnungen              : {len(self.warnings)}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #

@dataclass
class BuildConfig:
    """Parameter für die Kontur-Berechnung."""
    # Z-Ebenen-Toleranz
    z_tolerance: float = 0.01

    # Räumliche Toleranz für Kontur-Zusammenhang
    spatial_tolerance: float = 0.05

    # Bogenauflösung in mm
    arc_resolution: float = 0.1

    # Minimale Konturlänge
    min_contour_length: float = 1.0

    # Minimale Anzahl Punkte
    min_points: int = 4

    # Werkzeugradius-Rückrechnung aktivieren
    apply_cutter_comp: bool = True

    # XY-Toleranz für das Zusammenfassen gleicher Konturen über Z
    contour_match_tolerance: float = 0.1


# --------------------------------------------------------------------------- #
# Kernfunktion
# --------------------------------------------------------------------------- #

def build_paths(
    parse_result: ParseResult,
    config: Optional[BuildConfig] = None,
    tool_diameters: Optional[Dict[int, float]] = None,
) -> PathBuildResult:
    """
    Erzeugt aus dem ParseResult die Endkonturen und Bohrungen.

    Parameter:
        parse_result    – Ergebnis des G-Code-Parsers
        config          – BuildConfig
        tool_diameters  – Dict {Werkzeugnummer: Durchmesser} in mm
    """
    config = config or BuildConfig()
    tool_diameters = tool_diameters or {}
    result = PathBuildResult()

    # 1) Bewegungen nach Werkzeug gruppieren
    by_tool: Dict[int, List[Motion]] = {}
    for m in parse_result.motions:
        if m.tool is not None and m.is_cutting():
            by_tool.setdefault(m.tool, []).append(m)

    # 2) Pro Werkzeug Konturen bauen
    for tool, motions in sorted(by_tool.items()):
        contours = _build_contours_for_tool(
            motions, tool, config)
        result.by_tool[tool] = contours

        # 3) Radiusrückrechnung
        diameter = tool_diameters.get(tool, 0.0)
        for c in contours:
            result.theoretical.append(c)
            if (config.apply_cutter_comp
                    and c.cutter_comp != CutterComp.OFF
                    and diameter > 0):
                result.actual.append(
                    _reverse_cutter_compensation(c, diameter))
            else:
                result.actual.append(c)

    # 4) Bohrungen erkennen (CYCLE81 aus dem Programm)
    result.holes = _detect_holes(parse_result, tool_diameters)

    return result


# --------------------------------------------------------------------------- #
# Konturen pro Werkzeug
# --------------------------------------------------------------------------- #

def _build_contours_for_tool(
    motions: List[Motion],
    tool: int,
    config: BuildConfig,
) -> List[Contour]:
    """
    Baut aus den Bewegungen eines Werkzeugs die Konturen.

    Ansatz:
    1. Alle Bewegungen nach Z-Ebene gruppieren (mit Toleranz)
    2. Innerhalb jeder Z-Ebene zusammenhängende Ketten bilden
    3. Ketten über Z-Ebenen hinweg matchen → Endkonturen
    """
    if not motions:
        return []

    # Schritt 1: Z-Ebenen finden
    # Repräsentativer Z-Wert pro Bewegung: Mittelwert aus Start und Ende
    z_avg = [(m.start[2] + m.end[2]) / 2.0 for m in motions]

    # Gruppieren: gleiche Z-Ebene (Toleranz)
    groups: List[List[Motion]] = []
    for m, z in zip(motions, z_avg):
        placed = False
        for grp in groups:
            if abs(grp[0].end[2] - m.end[2]) <= config.z_tolerance:
                grp.append(m)
                placed = True
                break
        if not placed:
            groups.append([m])

    # Schritt 2: Innerhalb jeder Gruppe Ketten bilden
    all_raw_chains: List[Tuple[float, np.ndarray, List[int], CutterComp]] = []
    for grp in groups:
        chains = _split_into_chains(grp, config)
        for chain_motions in chains:
            pts, lines = _chain_to_points(chain_motions, config)
            if len(pts) < config.min_points:
                continue
            arr = np.array(pts, dtype=float)
            # Länge
            diffs = np.diff(arr, axis=0)
            length = float(np.sum(np.hypot(diffs[:, 0], diffs[:, 1])))
            if length < config.min_contour_length:
                continue
            z = min(m.end[2] for m in chain_motions)
            comp = chain_motions[0].cutter_comp
            all_raw_chains.append((z, arr, lines, comp))

    # Schritt 3: Ketten mit gleicher XY-Form zusammenfassen → tiefste behalten
    merged: List[Contour] = []
    used = [False] * len(all_raw_chains)

    # Sortiere nach Z aufsteigend (tiefste zuerst)
    order = sorted(range(len(all_raw_chains)),
                   key=lambda i: all_raw_chains[i][0])

    for idx in order:
        if used[idx]:
            continue
        z, arr, lines, comp = all_raw_chains[idx]

        # Suche andere Ketten mit gleicher XY-Form
        similar: List[int] = [idx]
        for j in range(len(all_raw_chains)):
            if used[j] or j == idx:
                continue
            z2, arr2, lines2, comp2 = all_raw_chains[j]
            if _contours_similar(arr, arr2, config.contour_match_tolerance):
                similar.append(j)

        for j in similar:
            used[j] = True

        # Tiefste Z-Ebene: die mit dem kleinsten Z
        deepest = min([all_raw_chains[j] for j in similar],
                      key=lambda t: t[0])
        z_deep, arr_deep, lines_deep, comp_deep = deepest

        # Geschlossen?
        closed = bool(np.allclose(arr_deep[0], arr_deep[-1], atol=0.05))

        # Länge
        diffs = np.diff(arr_deep, axis=0)
        length = float(np.sum(np.hypot(diffs[:, 0], diffs[:, 1])))

        merged.append(Contour(
            points=arr_deep,
            z=z_deep,
            tool=tool,
            closed=closed,
            cutter_comp=comp_deep,
            length=length,
            source_lines=lines_deep,
        ))

    return merged


def _split_into_chains(
    motions: List[Motion],
    config: BuildConfig,
) -> List[List[Motion]]:
    """
    Teilt die Bewegungen einer Z-Ebene in zusammenhängende Ketten.

    Neue Kette beginnt, wenn:
    - vorherige Bewegung nicht dort endet, wo die aktuelle beginnt (>0,1 mm)
    - große Richtungsänderung (nur wenn > 150° in einem Zug)
    """
    if not motions:
        return []

    chains: List[List[Motion]] = []
    current: List[Motion] = []
    last_end: Optional[Tuple[float, float, float]] = None

    for m in motions:
        if last_end is None:
            current.append(m)
            last_end = m.end
            continue

        # Distanz zwischen Vorgänger-Ende und Start
        d = math.hypot(m.start[0] - last_end[0],
                       m.start[1] - last_end[1])

        if d > config.spatial_tolerance:
            # Neue Kette
            if current:
                chains.append(current)
            current = [m]
        else:
            current.append(m)

        last_end = m.end

    if current:
        chains.append(current)

    return chains


def _chain_to_points(
    motions: List[Motion],
    config: BuildConfig,
) -> Tuple[List[Tuple[float, float]], List[int]]:
    """Wandelt eine Bewegungskette in eine Punktfolge um (Bögen aufgelöst)."""
    if not motions:
        return [], []

    points: List[Tuple[float, float]] = [
        (motions[0].start[0], motions[0].start[1])
    ]
    source_lines: List[int] = []

    for m in motions:
        if m.motion_type == MotionType.LINEAR:
            points.append((m.end[0], m.end[1]))
            source_lines.append(m.line_no)
        elif m.motion_type in (MotionType.ARC_CW, MotionType.ARC_CCW):
            arc_pts = _discretize_arc(m, config.arc_resolution)
            points.extend(arc_pts[1:])
            source_lines.append(m.line_no)
        else:
            points.append((m.end[0], m.end[1]))
            source_lines.append(m.line_no)

    return points, source_lines


# --------------------------------------------------------------------------- #
# Kontur-Vergleich (für Zusammenfassung über Z-Ebenen)
# --------------------------------------------------------------------------- #

def _contours_similar(
    a: np.ndarray,
    b: np.ndarray,
    tolerance: float,
) -> bool:
    """
    Prüft, ob zwei Punktfolgen die gleiche XY-Kontur beschreiben.

    Methode: Vergleich der Bounding-Boxen und der Punktanzahl.
    """
    if len(a) == 0 or len(b) == 0:
        return False

    # Bounding-Box-Vergleich
    ax0, ay0, ax1, ay1 = a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()
    bx0, by0, bx1, by1 = b[:, 0].min(), b[:, 1].min(), b[:, 0].max(), b[:, 1].max()

    if (abs(ax0 - bx0) > tolerance
            or abs(ay0 - by0) > tolerance
            or abs(ax1 - bx1) > tolerance
            or abs(ay1 - by1) > tolerance):
        return False

    # Punktanzahl: nicht zu unterschiedlich
    ratio = len(a) / max(1, len(b))
    if ratio < 0.7 or ratio > 1.4:
        return False

    return True


# --------------------------------------------------------------------------- #
# Bogen-Diskretisierung
# --------------------------------------------------------------------------- #

def _discretize_arc(motion: Motion,
                    resolution: float) -> List[Tuple[float, float]]:
    """Wandelt einen Kreisbogen in eine Punktfolge um."""
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
# Radiusrückrechnung
# --------------------------------------------------------------------------- #

def _reverse_cutter_compensation(contour: Contour,
                                 tool_diameter: float) -> Contour:
    """
    Rechnet den Werkzeugradius heraus.

    G41 (links vom Weg) → Kontur ist rechts vom Weg
    G42 (rechts vom Weg) → Kontur ist links vom Weg
    """
    if len(contour.points) < 2:
        return contour

    if contour.cutter_comp == CutterComp.LEFT:
        side = -1.0
    elif contour.cutter_comp == CutterComp.RIGHT:
        side = 1.0
    else:
        return contour

    offset = tool_diameter / 2.0
    pts = contour.points
    n = len(pts)
    new_pts = np.zeros_like(pts)

    for i in range(n):
        if i == 0:
            direction = pts[1] - pts[0]
        elif i == n - 1:
            direction = pts[-1] - pts[-2]
        else:
            direction = pts[i + 1] - pts[i - 1]

        length = np.hypot(direction[0], direction[1])
        if length < 1e-9:
            new_pts[i] = pts[i]
            continue

        nx = -direction[1] / length
        ny = direction[0] / length
        new_pts[i, 0] = pts[i, 0] + side * offset * nx
        new_pts[i, 1] = pts[i, 1] + side * offset * ny

    return Contour(
        points=new_pts,
        z=contour.z,
        tool=contour.tool,
        closed=contour.closed,
        cutter_comp=contour.cutter_comp,
        length=contour.length,
        source_lines=contour.source_lines,
    )


# --------------------------------------------------------------------------- #
# Bohrungen erkennen
# --------------------------------------------------------------------------- #

def _detect_holes(
    parse_result: ParseResult,
    tool_diameters: Dict[int, float],
) -> List[Hole]:
    """
    Erkennt Bohrungen aus dem Programm.

    Zwei Methoden:
    1. Isolierte G1-Z-Bewegungen (z. B. T1 mit G1 Z-10 F100)
    2. CYCLE81-Zyklen – kommen in den Motion-Daten als G0-Positionen vor
       (können nur über die Positionsabfolge erkannt werden)
    """
    holes: List[Hole] = []

    # Ansatz 1: Isolierte G1-Z-Bewegungen
    # Suche nach G1-Bewegungen, die nur in Z gehen und in einer
    # charakteristischen XY-Position stehen.
    last_xy: Optional[Tuple[float, float]] = None
    last_tool: Optional[int] = None

    for m in parse_result.motions:
        # Bewegung in Z (nur Z ändert sich)
        dz = abs(m.end[2] - m.start[2])
        dxy = math.hypot(m.end[0] - m.start[0], m.end[1] - m.start[1])

        if (m.motion_type == MotionType.LINEAR
                and dz > 0.5
                and dxy < 0.01
                and m.end[2] < m.start[2] - 0.5):    # abwärts
            # Tiefe erreicht
            if last_xy is None or last_tool != m.tool:
                last_xy = (m.start[0], m.start[1])
                last_tool = m.tool
            diameter = tool_diameters.get(m.tool or 0, 0.0)
            holes.append(Hole(
                x=m.start[0], y=m.start[1],
                z_top=m.start[2], z_bottom=m.end[2],
                tool=m.tool or 0,
                diameter=diameter,
                source_line=m.line_no,
            ))

    # Ansatz 2: Wenn CYCLE81 im Programm ist, aus den G0-Positionen
    if "CYCLE81" in parse_result.cycles:
        holes.extend(_detect_holes_from_cycle(parse_result, tool_diameters))

    # Deduplizieren (Position + Tool)
    seen = set()
    unique: List[Hole] = []
    for h in holes:
        key = (round(h.x, 2), round(h.y, 2), h.tool)
        if key in seen:
            continue
        seen.add(key)
        unique.append(h)

    return unique


def _detect_holes_from_cycle(
    parse_result: ParseResult,
    tool_diameters: Dict[int, float],
) -> List[Hole]:
    """
    Erkennt Bohrungen aus einem CYCLE81-Zyklus.

    Idee: Nach `MCALL CYCLE81(...)` folgen mehrere G0-Positionen
    (nur X/Y), die die Bohrpositionen markieren. Vor dem abschließenden
    `MCALL` (ohne Parameter) endet der Zyklus.
    """
    holes: List[Hole] = []
    in_cycle = False
    cycle_depth = -10.0
    cycle_tool: Optional[int] = None
    cycle_top = 0.0

    for m in parse_result.motions:
        # Wir prüfen die Raw-Line auf MCALL / CYCLE
        raw = m.raw_line.upper()
        if "CYCLE81" in raw and "MCALL" in raw:
            in_cycle = True
            cycle_tool = m.tool
            # Parameter aus CYCLE81(5, -10, 5, -10, ) lesen:
            # (Sicherheitsabstand, Bezug, ...)
            # Konservativ: letzte Zahl als Bohrtiefe
            import re
            nums = re.findall(r"-?\d+(?:\.\d+)?", raw)
            if len(nums) >= 2:
                try:
                    cycle_depth = float(nums[-2])
                except ValueError:
                    pass
            continue

        if in_cycle and "MCALL" in raw and "CYCLE" not in raw:
            in_cycle = False
            continue

        if in_cycle and m.motion_type == MotionType.RAPID:
            # Position im Zyklus → Bohrung
            dxy = math.hypot(m.end[0] - m.start[0], m.end[1] - m.start[1])
            if dxy > 0.1:
                diameter = tool_diameters.get(cycle_tool or 0, 0.0)
                holes.append(Hole(
                    x=m.end[0], y=m.end[1],
                    z_top=cycle_top, z_bottom=cycle_depth,
                    tool=cycle_tool or 0,
                    diameter=diameter,
                    source_line=m.line_no,
                ))

    return holes