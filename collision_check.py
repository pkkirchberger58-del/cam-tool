"""
collision_check.py
------------------
Heuristische Prüfung eines G-Code-Programms auf gefährliche
Schnelllauf-Bewegungen (G0) durch Material.

Die Prüfung ist bewusst konservativ: lieber ein Warnhinweis zu viel
als ein Werkzeugbruch zu wenig. Sie arbeitet in 2D (XY) – Z wird nur
über die Sicherheitshöhe bewertet.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Sequence

import numpy as np

from dxf_loader import Contour


# --------------------------------------------------------------------------- #

@dataclass
class Warning:
    line_no: int            # 1-basierte Zeilennummer im G-Code
    severity: str           # "kritisch" | "warnung" | "info"
    message: str
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None

    def short(self) -> str:
        loc = ""
        if self.x is not None and self.y is not None:
            loc = f" @ ({self.x:.2f}, {self.y:.2f})"
            if self.z is not None:
                loc += f" Z{self.z:.2f}"
        return f"Zeile {self.line_no}: [{self.severity}] {self.message}{loc}"


@dataclass
class MachineState:
    x: float = 0.0
    y: float = 0.0
    z: float = 100.0
    feed_mode: str = "G0"   # aktueller Modus


# --------------------------------------------------------------------------- #

_LINE_RE = re.compile(
    r"""^\s*
        (?P<cmd>G0?[0-3]|G00|G01|G02|G03)?       # Bewegungsbefehl
        (?P<rest>.*)$
    """, re.VERBOSE | re.IGNORECASE)

_WORD_RE = re.compile(r"([A-Z])\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)


def _parse_words(line: str) -> dict:
    """Extrahiert alle Adressbuchstaben A–Z mit ihren Zahlwerten."""
    words: dict[str, float] = {}
    for letter, value in _WORD_RE.findall(line):
        words[letter.upper()] = float(value)
    return words


def _segments_intersect(p1, p2, p3, p4) -> bool:
    """2D-Segment-Schnitt (echter Schnitt, keine Kollinearität)."""
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    d1 = cross(p3, p4, p1)
    d2 = cross(p3, p4, p2)
    d3 = cross(p1, p2, p3)
    d4 = cross(p1, p2, p4)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def _point_in_polygon(pt, poly: np.ndarray) -> bool:
    """Ray-Casting – funktioniert für einfache, geschlossene Polygone."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and \
           (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1):
            inside = not inside
    return inside


# --------------------------------------------------------------------------- #

def check_program(
    gcode: str,
    contours: Sequence[Contour],
    safe_z: float,
    rapid_feed_warning: bool = True,
) -> List[Warning]:
    """
    Prüft ein komplettes G-Code-Programm und gibt alle Warnungen zurück.

    Parameter:
        gcode                 – der komplette G-Code als String
        contours              – Konturen aus dem DXF (für Wand-Schnitt-Check)
        safe_z                – Sicherheitshöhe (Z-Wert, oberhalb der roh ist)
        rapid_feed_warning    – auch G1/G2/G3 in der Luft melden (info)
    """
    warnings: List[Warning] = []
    state = MachineState()

    # Schnelle Suche: 2D-Bounding-Boxen der Konturen
    contour_boxes = []
    for c in contours:
        if len(c.points) < 2:
            continue
        pts = c.points
        contour_boxes.append((
            pts[:, 0].min(), pts[:, 1].min(),
            pts[:, 0].max(), pts[:, 1].max(),
            pts,
        ))

    def line_hits_any_contour(p_from, p_to) -> Optional[int]:
        """Gibt Index der ersten getroffenen Kontur zurück oder None."""
        # Schnelle BBox-Vorfilterung
        xmin, xmax = sorted((p_from[0], p_to[0]))
        ymin, ymax = sorted((p_from[1], p_to[1]))
        for idx, (cx0, cy0, cx1, cy1, pts) in enumerate(contour_boxes):
            if xmax < cx0 or xmin > cx1 or ymax < cy0 or ymin > cy1:
                continue
            # Segmentweise prüfen
            for i in range(len(pts) - 1):
                if _segments_intersect(p_from, p_to, pts[i], pts[i + 1]):
                    return idx
        return None

    def start_inside_any_contour(pt) -> Optional[int]:
        for idx, (_cx0, _cy0, _cx1, _cy1, pts) in enumerate(contour_boxes):
            if _point_in_polygon(pt, pts):
                return idx
        return None

    in_block_comment = False
    for lineno, raw_line in enumerate(gcode.splitlines(), start=1):
        # Kommentare entfernen
        line = raw_line.split(";")[0]
        if in_block_comment:
            if ")" in line:
                line = line.split(")", 1)[1]
                in_block_comment = False
            else:
                continue
        if "(" in line:
            before, _, after = line.partition("(")
            if ")" in after:
                after = after.split(")", 1)[1]
                line = before + after
            else:
                line = before
                in_block_comment = True

        if not line.strip():
            continue

        m = _LINE_RE.match(line)
        if not m:
            continue
        cmd = (m.group("cmd") or "").upper()
        if cmd in ("G00",): cmd = "G0"
        if cmd in ("G01",): cmd = "G1"
        if cmd in ("G02",): cmd = "G2"
        if cmd in ("G03",): cmd = "G3"

        words = _parse_words(line)

        # Modus übernehmen, wenn angegeben
        if cmd:
            state.feed_mode = cmd

        new_x = words.get("X", state.x)
        new_y = words.get("Y", state.y)
        new_z = words.get("Z", state.z)

        # ----------------------------------------------------- Regel 2 ----
        if state.feed_mode == "G0" and new_z < 0 and \
                (new_x != state.x or new_y != state.y):
            warnings.append(Warning(
                line_no=lineno, severity="kritisch",
                message="G0 mit Z unter Materialoberfläche und XY-Bewegung.",
                x=new_x, y=new_y, z=new_z))

        # ----------------------------------------------------- Regel 1 ----
        if state.feed_mode == "G0" and new_z < safe_z and \
                (new_x != state.x or new_y != state.y):
            hit = line_hits_any_contour((state.x, state.y), (new_x, new_y))
            if hit is not None:
                warnings.append(Warning(
                    line_no=lineno, severity="kritisch",
                    message=(
                        f"G0-Schräglauf kreuzt Kontur #{hit+1} "
                        f"unterhalb Sicherheitshöhe (Z{safe_z:.1f})."
                    ),
                    x=new_x, y=new_y, z=new_z))

        # ----------------------------------------------------- Regel 4 ----
        if state.feed_mode == "G0" and new_z < safe_z and \
                (new_x != state.x or new_y != state.y):
            inside_start = start_inside_any_contour((state.x, state.y))
            inside_end = start_inside_any_contour((new_x, new_y))
            if inside_start is not None and inside_end is None:
                warnings.append(Warning(
                    line_no=lineno, severity="warnung",
                    message=(
                        f"G0 führt aus Kontur #{inside_start+1} heraus "
                        f"(unterhalb Sicherheitshöhe)."
                    ),
                    x=new_x, y=new_y, z=new_z))

        # ----------------------------------------------------- Regel 3 ----
        if rapid_feed_warning and state.feed_mode in ("G1", "G2", "G3") and \
                new_z > safe_z * 0.9 and (new_x != state.x or new_y != state.y):
            warnings.append(Warning(
                line_no=lineno, severity="info",
                message="Vorschubbewegung oberhalb der Sicherheitshöhe "
                        "(evtl. Tippfehler im Programm).",
                x=new_x, y=new_y, z=new_z))

        # Zustand fortschreiben
        state.x, state.y, state.z = new_x, new_y, new_z

    return warnings


# --------------------------------------------------------------------------- #

def summarize(warnings: List[Warning]) -> str:
    """Kurze Zusammenfassung für Statuszeile / Dialog."""
    if not warnings:
        return "Keine verdächtigen G0-Bewegungen gefunden."
    kritisch = sum(1 for w in warnings if w.severity == "kritisch")
    warnung = sum(1 for w in warnings if w.severity == "warnung")
    info = sum(1 for w in warnings if w.severity == "info")
    parts = []
    if kritisch: parts.append(f"{kritisch} kritisch")
    if warnung:  parts.append(f"{warnung} Warnung(en)")
    if info:     parts.append(f"{info} Hinweis(e)")
    return " · ".join(parts) if parts else "Keine Warnungen."