"""
gcode_parser.py
---------------
Parser für Sinumerik G-Code-Programme (mit Fusion-360-Erweiterungen).

Unterstützt:
- G0 / G1 / G2 / G3
- G17 / G18 / G19 (Ebenen mit korrekter I/J/K-Interpretation)
- G40 / G41 / G42 (Radiuskorrektur)
- G54 – G59 (Nullpunktverschiebungen)
- T / M6 (Werkzeugwechsel), D1 (Schneidendaten)
- S / F / M3 / M4 / M5 / M8 / M9
- Helix-Bewegungen (G2/G3 mit gleichzeitiger X/Y/Z-Bewegung)
- Modal fortgeführte G2/G3 (I/J/K aus vorheriger Zeile)
- CR= (Fusion 360 Kreisradius) und R (Standard)
- SUPA (Schnellabheben – wird ignoriert)
- MCALL CYCLE81 / CYCLE83 / … (nur erkannt, nicht ausgeführt)

Kommentare:
- ; ...       (Zeilenkommentar)
- ( ... )     (Blockkommentar)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


# --------------------------------------------------------------------------- #
# Datenklassen
# --------------------------------------------------------------------------- #

class MotionType(Enum):
    RAPID = "G0"
    LINEAR = "G1"
    ARC_CW = "G2"
    ARC_CCW = "G3"
    UNKNOWN = "?"


class Plane(Enum):
    XY = "G17"
    ZX = "G18"
    YZ = "G19"


class CutterComp(Enum):
    OFF = "G40"
    LEFT = "G41"
    RIGHT = "G42"


@dataclass
class MachineState:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    f: Optional[float] = None
    s: Optional[int] = None
    tool: Optional[int] = None            # aktuell aktives Werkzeug
    pending_tool: Optional[int] = None    # vorbereitetes Werkzeug (T… ohne M6)
    d_number: int = 1                     # Schneidendaten (D1)
    motion: MotionType = MotionType.RAPID
    plane: Plane = Plane.XY
    cutter_comp: CutterComp = CutterComp.OFF
    work_offset: str = "G54"
    # Für modal fortgeführte Bögen
    last_i: Optional[float] = None
    last_j: Optional[float] = None
    last_k: Optional[float] = None
    # Für modal fortgeführte Bewegung
    last_motion: Optional[MotionType] = None

    def copy(self) -> "MachineState":
        return MachineState(
            x=self.x, y=self.y, z=self.z,
            f=self.f, s=self.s,
            tool=self.tool,
            pending_tool=self.pending_tool,
            d_number=self.d_number,
            motion=self.motion, plane=self.plane,
            cutter_comp=self.cutter_comp,
            work_offset=self.work_offset,
            last_i=self.last_i, last_j=self.last_j, last_k=self.last_k,
            last_motion=self.last_motion,
        )


@dataclass
class Motion:
    line_no: int
    motion_type: MotionType
    start: Tuple[float, float, float]
    end: Tuple[float, float, float]
    feed: Optional[float] = None
    tool: Optional[int] = None
    cutter_comp: CutterComp = CutterComp.OFF
    plane: Plane = Plane.XY
    arc_center: Optional[Tuple[float, float, float]] = None
    arc_radius: Optional[float] = None
    is_helix: bool = False
    raw_line: str = ""

    def length_xy(self) -> float:
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        return math.hypot(dx, dy)

    def is_cutting(self) -> bool:
        return self.motion_type in (
            MotionType.LINEAR, MotionType.ARC_CW, MotionType.ARC_CCW)


@dataclass
class ParseResult:
    motions: List[Motion] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    program_number: str = ""
    tool_changes: List[int] = field(default_factory=list)
    cycles: List[str] = field(default_factory=list)

    @property
    def cutting_motions(self) -> List[Motion]:
        return [m for m in self.motions if m.is_cutting()]

    @property
    def max_z(self) -> float:
        return max((m.end[2] for m in self.motions), default=0.0)

    @property
    def min_z(self) -> float:
        return min((m.end[2] for m in self.motions), default=0.0)


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

# Erweiterte Wort-Erkennung: normale Wörter UND CR= / R= / SUPA
_WORD_PATTERN = re.compile(r"([A-Z]+)\s*=?\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_CYCLE_PATTERN = re.compile(
    r"(MCALL\s+)?(CYCLE\d+|L\d+|CYCL\s+DEF\s+\d+)", re.IGNORECASE)
_PROG_NUMBER_PATTERN = re.compile(r"%_N_(\S+?)(?:\s|$)")


class SinumerikParser:
    """Parser für Sinumerik G-Code-Programme mit Fusion-360-Erweiterungen."""

    def __init__(self) -> None:
        self._reset()

    # ------------------------------------------------------------------ #

    def _reset(self) -> None:
        self.state = MachineState()
        self.result = ParseResult()

    # ------------------------------------------------------------------ #

    def parse(self, text: str) -> ParseResult:
        self._reset()
        in_block_comment = False

        for lineno, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line

            # Programmnummer erkennen – auch in Kommentaren!
            if not self.result.program_number:
                stripped = raw_line.strip()
                if stripped.startswith("%") and "_N_" in stripped:
                    self.result.program_number = stripped
                elif "%" in stripped and "_N_" in stripped:
                    m = _PROG_NUMBER_PATTERN.search(stripped)
                    if m:
                        self.result.program_number = m.group(1)

            # Blockkommentar
            if in_block_comment:
                if ")" in line:
                    line = line.split(")", 1)[1]
                    in_block_comment = False
                else:
                    continue

            # Zeilenkommentar
            if ";" in line:
                line = line.split(";", 1)[0]

            # Blockkommentar inline
            while "(" in line:
                before, _, after = line.partition("(")
                if ")" in after:
                    after = after.split(")", 1)[1]
                    line = before + after
                else:
                    line = before
                    in_block_comment = True
                    break

            if not line.strip():
                continue

            # Zyklen erkennen (CYCLE81, CYCL DEF …)
            cycle_match = _CYCLE_PATTERN.search(line)
            if cycle_match:
                cycle_name = cycle_match.group(2).strip()
                if cycle_name not in self.result.cycles:
                    self.result.cycles.append(cycle_name)

            # Zeile parsen
            try:
                self._parse_line(line.strip(), lineno)
            except Exception as exc:  # noqa: BLE001
                self.result.errors.append(
                    f"Zeile {lineno}: {type(exc).__name__}: {exc}  "
                    f"[{raw_line.strip()}]")

        return self.result

    # ------------------------------------------------------------------ #

    def _parse_line(self, line: str, lineno: int) -> None:
        words = _WORD_PATTERN.findall(line)
        if not words:
            return

        # Wörter in Dict wandeln
        word_dict: dict[str, list[float]] = {}
        for letter, value in words:
            letter = letter.upper()
            try:
                value = float(value)
            except ValueError:
                continue
            word_dict.setdefault(letter, []).append(value)

        new_state = self.state.copy()
        motion_type_this_line: Optional[MotionType] = None

        # 1) G-Codes
        for g_val in word_dict.get("G", []):
            self._apply_g_code(g_val, new_state,
                               holder := [motion_type_this_line])
            motion_type_this_line = holder[0]

        # Werkzeug / D-Nummer
        # WICHTIG: In Sinumerik wird "T…" oft zur VORBEREITUNG des NÄCHSTEN
        # Werkzeugs verwendet. Erst "M6" führt den echten Wechsel aus.
        if "T" in word_dict:
            new_state.pending_tool = int(word_dict["T"][0])
        if "D" in word_dict:
            new_state.d_number = int(word_dict["D"][0])

        # Drehzahl / Vorschub
        if "S" in word_dict:
            new_state.s = int(word_dict["S"][0])
        if "F" in word_dict:
            new_state.f = float(word_dict["F"][0])

        # M-Befehle
        for m_val in word_dict.get("M", []):
            m_int = int(m_val)
            if m_int == 6:
                # Erst jetzt wird das vorbereitete Werkzeug aktiv
                if new_state.pending_tool is not None:
                    new_state.tool = new_state.pending_tool
                    if new_state.tool not in self.result.tool_changes:
                        self.result.tool_changes.append(new_state.tool)
            if m_int == 30:
                new_state.motion = MotionType.RAPID

        # 2) Bewegung?
        has_motion = any(k in word_dict for k in ("X", "Y", "Z", "I", "J", "K"))
        has_arc_word = ("CR" in word_dict or "R" in word_dict)

        if not has_motion and not has_arc_word:
            self.state = new_state
            return

        # Ziel-Koordinaten
        x_new = word_dict.get("X", [self.state.x])[0]
        y_new = word_dict.get("Y", [self.state.y])[0]
        z_new = word_dict.get("Z", [self.state.z])[0]

        # ------------------------------------------------------------------
        # Bewegungstyp bestimmen
        # ------------------------------------------------------------------
        # Regel: Es gibt immer genau EINEN aktiven Modus pro Zeitpunkt.
        # - Wenn in DIESER Zeile ein G0/G1/G2/G3 steht → dieser gilt
        # - Sonst → der Modus aus der vorherigen Zeile (self.state.motion)
        if motion_type_this_line is not None:
            move_type = motion_type_this_line
        else:
            move_type = self.state.motion

        new_state.motion = move_type

        # ------------------------------------------------------------------
        # Bogen-Verarbeitung (nur wenn wirklich ein Bogen gefahren wird)
        # ------------------------------------------------------------------
        arc_center = None
        arc_radius = None
        is_helix = False

        if move_type in (MotionType.ARC_CW, MotionType.ARC_CCW):
            arc_center, arc_radius = self._compute_arc(
                word_dict, new_state, x_new, y_new, z_new, move_type)

            if arc_center is None:
                self.result.warnings.append(
                    f"Zeile {lineno}: Bogen unvollständig, als Gerade "
                    f"interpretiert.")
                move_type = MotionType.LINEAR
                new_state.motion = MotionType.LINEAR
            else:
                if abs(z_new - self.state.z) > 1e-6:
                    is_helix = True

        # ------------------------------------------------------------------
        # Motion erzeugen
        # ------------------------------------------------------------------
        motion = Motion(
            line_no=lineno,
            motion_type=move_type,
            start=(self.state.x, self.state.y, self.state.z),
            end=(x_new, y_new, z_new),
            feed=new_state.f,
            tool=new_state.tool,
            cutter_comp=new_state.cutter_comp,
            plane=new_state.plane,
            arc_center=arc_center,
            arc_radius=arc_radius,
            is_helix=is_helix,
            raw_line=line,
        )
        self.result.motions.append(motion)

        # Zustand aktualisieren
        new_state.x, new_state.y, new_state.z = x_new, y_new, z_new
        self.state = new_state

    # ------------------------------------------------------------------ #

    def _compute_arc(
        self,
        word_dict: dict,
        state: MachineState,
        x_new: float, y_new: float, z_new: float,
        move_type: MotionType,
    ) -> Tuple[Optional[Tuple[float, float, float]], Optional[float]]:
        """
        Berechnet Mittelpunkt und Radius eines Bogens.

        Unterstützt:
        - I/J/K (ebenenabhängig)
        - R (Standard)
        - CR= (Fusion 360)
        - Modal fortgeführte I/J/K
        """
        i_val = word_dict.get("I", [None])[0]
        j_val = word_dict.get("J", [None])[0]
        k_val = word_dict.get("K", [None])[0]

        has_ijk = (i_val is not None or j_val is not None or k_val is not None)

        # Modal: aus vorherigem Zustand übernehmen
        if not has_ijk and state.last_i is not None:
            i_val = state.last_i
            j_val = state.last_j
            k_val = state.last_k
            has_ijk = True

        if has_ijk:
            # Ebene berücksichtigen!
            if state.plane == Plane.XY:
                i = i_val if i_val is not None else 0.0
                j = j_val if j_val is not None else 0.0
                k = k_val if k_val is not None else 0.0
                cx = state.x + i
                cy = state.y + j
                cz = state.z + k
            elif state.plane == Plane.ZX:
                i = i_val if i_val is not None else 0.0
                j = j_val if j_val is not None else 0.0
                k = k_val if k_val is not None else 0.0
                cx = state.x + k
                cy = state.y + 0.0
                cz = state.z + j
            else:  # YZ
                i = i_val if i_val is not None else 0.0
                j = j_val if j_val is not None else 0.0
                k = k_val if k_val is not None else 0.0
                cx = state.x + 0.0
                cy = state.y + i
                cz = state.z + j

            # Merken für modale Fortführung
            state.last_i = i_val
            state.last_j = j_val
            state.last_k = k_val

            # Radius aus Abstand
            if state.plane == Plane.XY:
                r = math.hypot(state.x - cx, state.y - cy)
            elif state.plane == Plane.ZX:
                r = math.hypot(state.x - cx, state.z - cz)
            else:
                r = math.hypot(state.y - cy, state.z - cz)

            return (cx, cy, cz), r

        # Radius-Methode (R oder CR)
        r_val = word_dict.get("R", [None])[0]
        if r_val is None:
            r_val = word_dict.get("CR", [None])[0]

        if r_val is not None:
            if state.plane == Plane.XY:
                start2d = (state.x, state.y)
                end2d = (x_new, y_new)
            elif state.plane == Plane.ZX:
                start2d = (state.x, state.z)
                end2d = (x_new, z_new)
            else:
                start2d = (state.y, state.z)
                end2d = (y_new, z_new)

            center2d = self._center_from_radius(
                start2d, end2d, r_val, move_type)
            if center2d is None:
                return None, None

            c1, c2 = center2d
            if state.plane == Plane.XY:
                cx, cy, cz = c1, c2, state.z
            elif state.plane == Plane.ZX:
                cx, cy, cz = c1, state.y, c2
            else:
                cx, cy, cz = state.x, c1, c2
            return (cx, cy, cz), abs(r_val)

        return None, None

    # ------------------------------------------------------------------ #

    def _apply_g_code(self, g: float, state: MachineState,
                      motion_holder: list) -> None:
        g_int = int(g)

        if g_int == 0:
            motion_holder[0] = MotionType.RAPID
            return
        if g_int == 1:
            motion_holder[0] = MotionType.LINEAR
            return
        if g_int == 2:
            motion_holder[0] = MotionType.ARC_CW
            return
        if g_int == 3:
            motion_holder[0] = MotionType.ARC_CCW
            return

        if g_int == 17:
            state.plane = Plane.XY
            return
        if g_int == 18:
            state.plane = Plane.ZX
            return
        if g_int == 19:
            state.plane = Plane.YZ
            return

        if g_int == 40:
            state.cutter_comp = CutterComp.OFF
            return
        if g_int == 41:
            state.cutter_comp = CutterComp.LEFT
            return
        if g_int == 42:
            state.cutter_comp = CutterComp.RIGHT
            return

        if 54 <= g_int <= 59:
            state.work_offset = f"G{g_int}"
            return

    # ------------------------------------------------------------------ #

    @staticmethod
    def _center_from_radius(start2d, end2d, r_signed, motion_type):
        x1, y1 = start2d
        x2, y2 = end2d
        r = abs(r_signed)
        dx = x2 - x1
        dy = y2 - y1
        d = math.hypot(dx, dy)

        if d > 2 * r + 1e-9 or d < 1e-9:
            return None

        h = math.sqrt(max(0.0, r * r - (d / 2) ** 2))
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        nx = -dy / d
        ny = dx / d

        if motion_type == MotionType.ARC_CW:
            sign = 1 if r_signed > 0 else -1
        else:
            sign = -1 if r_signed > 0 else 1

        return (mx + sign * h * nx, my + sign * h * ny)


# --------------------------------------------------------------------------- #
# Modul-Funktionen
# --------------------------------------------------------------------------- #

def parse_sinumerik(text: str) -> ParseResult:
    return SinumerikParser().parse(text)


def parse_file(path: str, encoding: str = "utf-8") -> ParseResult:
    with open(path, "r", encoding=encoding) as f:
        return parse_sinumerik(f.read())