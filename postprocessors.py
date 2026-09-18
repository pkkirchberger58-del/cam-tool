"""
postprocessors.py
-----------------
Postprozessoren für verschiedene Steuerungen.

Unterstützt:
- Sinumerik 840D / 828D  (G-Code, .mpf)
- Heidenhain TNC 640       (Klartext, .h)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class ProgramHeader:
    program_number: str = "1000"
    program_name: str = "TEIL"
    tool_number: int = 1
    spindle_speed: int = 3000
    feed_rate: int = 400
    coolant: bool = True
    safety_height: float = 50.0
    work_offset: str = "G54"          # Sinumerik: G54..G57, Heidenhain: CYCL DEF 247
    use_radius_comp: bool = False     # G41/G42 (Sinumerik), RL/RR (Heidenhain)
    radius_comp_side: str = "left"    # "left" / "right"


class PostProcessor:
    """Basisklasse – gibt reine G-Code-Befehle aus."""

    extension = ".nc"
    label = "Generisch"

    def header(self, cfg: ProgramHeader) -> List[str]:
        raise NotImplementedError

    def rapid(self, x=None, y=None, z=None) -> str:
        raise NotImplementedError

    def linear(self, x=None, y=None, z=None, f=None) -> str:
        raise NotImplementedError

    def arc(self, x, y, i, j, clockwise=False, f=None) -> str:
        raise NotImplementedError

    def drill(self, x, y, depth, retract) -> List[str]:
        raise NotImplementedError

    def footer(self) -> List[str]:
        raise NotImplementedError

    # Gemeinsame Helfer
    @staticmethod
    def _fmt(v: float) -> str:
        s = f"{v:.3f}".rstrip("0").rstrip(".")
        return s if s else "0"


# --------------------------------------------------------------------------- #
# Sinumerik 840D / 828D
# --------------------------------------------------------------------------- #
class Sinumerik840D(PostProcessor):
    extension = ".mpf"
    label = "Sinumerik 840D / 828D"

    def header(self, cfg: ProgramHeader) -> List[str]:
        lines = [
            f"; {cfg.program_name}",
            f"; Postprozessor: Sinumerik 840D",
            f"G90 G{cfg.work_offset[1:]} G17 G40 G71",
            f"T{cfg.tool_number} M6",
            f"S{cfg.spindle_speed} M3",
        ]
        if cfg.coolant:
            lines.append("M8")
        lines.append(f"G0 Z{self._fmt(cfg.safety_height)}")
        return lines

    def rapid(self, x=None, y=None, z=None) -> str:
        parts = ["G0"]
        if x is not None: parts.append(f"X{self._fmt(x)}")
        if y is not None: parts.append(f"Y{self._fmt(y)}")
        if z is not None: parts.append(f"Z{self._fmt(z)}")
        return " ".join(parts)

    def linear(self, x=None, y=None, z=None, f=None) -> str:
        parts = ["G1"]
        if x is not None: parts.append(f"X{self._fmt(x)}")
        if y is not None: parts.append(f"Y{self._fmt(y)}")
        if z is not None: parts.append(f"Z{self._fmt(z)}")
        if f is not None: parts.append(f"F{self._fmt(f)}")
        return " ".join(parts)

    def arc(self, x, y, i, j, clockwise=False, f=None) -> str:
        cmd = "G2" if clockwise else "G3"
        parts = [cmd, f"X{self._fmt(x)}", f"Y{self._fmt(y)}",
                 f"I{self._fmt(i)}", f"J{self._fmt(j)}"]
        if f is not None: parts.append(f"F{self._fmt(f)}")
        return " ".join(parts)

    def drill(self, x, y, depth, retract) -> List[str]:
        return [
            f"G0 X{self._fmt(x)} Y{self._fmt(y)}",
            "G0 Z2",
            f"G1 Z{self._fmt(depth)} F150",
            f"G0 Z{self._fmt(retract)}",
        ]

    def footer(self) -> List[str]:
        return ["M9", "M5", "G0 Z100", "M30"]


# --------------------------------------------------------------------------- #
# Heidenhain TNC (Klartext)
# --------------------------------------------------------------------------- #
class HeidenhainTNC(PostProcessor):
    extension = ".h"
    label = "Heidenhain TNC 640 (Klartext)"

    def header(self, cfg: ProgramHeader) -> List[str]:
        # Heidenhain: Programmnummer im Klartext, Werkzeugaufruf via TOOL CALL
        lines = [
            f"BEGIN PGM {cfg.program_number} {cfg.program_name} MM",
            "BLK FORM 0.1 Z X-100 Y-100 Z-50",
            "BLK FORM 0.2 X+100 Y+100 Z+0",
            f"TOOL CALL {cfg.tool_number} Z S{cfg.spindle_speed}",
            f"CYCL DEF 247 DATUM SETTING ~",
            f"  Q339=+1 ; DATUM NUMBER",
        ]
        if cfg.coolant:
            lines.append("M8")
        lines.append(f"L Z+{self._fmt(cfg.safety_height)} R0 FMAX")
        return lines

    def rapid(self, x=None, y=None, z=None) -> str:
        parts = ["L"]
        if x is not None: parts.append(f"X{self._signed(x)}")
        if y is not None: parts.append(f"Y{self._signed(y)}")
        if z is not None: parts.append(f"Z{self._signed(z)}")
        parts.append("R0 FMAX")
        return " ".join(parts)

    def linear(self, x=None, y=None, z=None, f=None) -> str:
        parts = ["L"]
        if x is not None: parts.append(f"X{self._signed(x)}")
        if y is not None: parts.append(f"Y{self._signed(y)}")
        if z is not None: parts.append(f"Z{self._signed(z)}")
        parts.append(f"R0 F{'MAX' if f is None else self._fmt(f)}")
        return " ".join(parts)

    def arc(self, x, y, i, j, clockwise=False, f=None) -> str:
        # Heidenhain: CC = Kreismittelpunkt, C = Kreisbogen
        cmd = "C" if not clockwise else "C"
        direction = "DR-" if clockwise else "DR+"
        lines = [
            f"CC X{self._signed(x - i)} Y{self._signed(y - j)}",
            f"{cmd} X{self._signed(x)} Y{self._signed(y)} {direction} "
            f"R0 F{'MAX' if f is None else self._fmt(f)}",
        ]
        return "\n".join(lines)

    def drill(self, x, y, depth, retract) -> List[str]:
        return [
            f"L X{self._signed(x)} Y{self._signed(y)} R0 FMAX",
            f"L Z+2 R0 FMAX",
            f"L Z{self._signed(depth)} R0 F150",
            f"L Z{self._signed(retract)} R0 FMAX",
        ]

    def footer(self) -> List[str]:
        return ["M9", "M5", "L Z+100 R0 FMAX", f"END PGM "]

    @staticmethod
    def _signed(v: float) -> str:
        s = f"{v:+.3f}".rstrip("0").rstrip(".")
        return s if s not in ("+", "-") else "+0"


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
POSTPROCESSORS = {
    "Sinumerik 840D / 828D": Sinumerik840D,
    "Heidenhain TNC 640":    HeidenhainTNC,
}


def create_postprocessor(name: str) -> PostProcessor:
    cls = POSTPROCESSORS.get(name, Sinumerik840D)
    return cls()