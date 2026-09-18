"""
app_state.py
------------
Zentrale Zustandsverwaltung für die GUI.

Speichert:
- Geladene Dateien (DXF, G-Code)
- Verifikations-Ergebnisse
- Einstellungen (Toleranz, Pfade)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from dxf_loader import DxfContent
from gcode_parser import ParseResult
from compare import VerificationResult


@dataclass
class AppState:
    """Zentraler Zustand der Anwendung."""

    # ---- Geladene Dateien ----
    dxf_path: Optional[str] = None
    dxf_content: Optional[DxfContent] = None

    gcode_path: Optional[str] = None
    gcode_result: Optional[ParseResult] = None

    # ---- Verifikations-Ergebnis ----
    verify_result: Optional[VerificationResult] = None

    # ---- Einstellungen ----
    tolerance: float = 0.01
    check_contours: bool = True
    check_holes: bool = True
    check_collisions: bool = True

    # ---- Letzte Ordner ----
    last_dxf_dir: str = ""
    last_gcode_dir: str = ""
    last_save_dir: str = ""

    # ---- Status ----
    current_view: str = "dashboard"   # "dashboard" | "workflow" | "result"

    def reset(self) -> None:
        """Setzt den Zustand für eine neue Prüfung zurück."""
        self.dxf_path = None
        self.dxf_content = None
        self.gcode_path = None
        self.gcode_result = None
        self.verify_result = None
        self.current_view = "dashboard"

    def has_dxf(self) -> bool:
        return self.dxf_content is not None

    def has_gcode(self) -> bool:
        return self.gcode_result is not None

    def has_result(self) -> bool:
        return self.verify_result is not None

    def file_summary_dxf(self) -> str:
        if not self.dxf_content:
            return "Keine Datei"
        return (f"{os.path.basename(self.dxf_path)} – "
                f"{len(self.dxf_content.contours)} Konturen, "
                f"{len(self.dxf_content.holes)} Kreise")

    def file_summary_gcode(self) -> str:
        if not self.gcode_result:
            return "Keine Datei"
        r = self.gcode_result
        fmt = "Sinumerik" if self.gcode_path.endswith((".mpf", ".nc")) else "G-Code"
        return (f"{os.path.basename(self.gcode_path)} – "
                f"{fmt}, {len(r.motions)} Bewegungen")