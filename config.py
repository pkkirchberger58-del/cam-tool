"""
config.py
---------
Speichert und lädt Anwendungseinstellungen in config.json.

Enthält:
- Fenstergeometrie
- Letzte Parameter (Werkzeug, Vorschub, ...)
- Zuletzt geladene Dateien
- Ausgewählter Postprozessor
- Rohteilhöhe und Zeichnungsmodus für die technische Zeichnung

Die Datei wird beim ersten Programmstart automatisch mit Standardwerten
angelegt und beim Schließen der Anwendung aktualisiert.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any


# Dateiname im aktuellen Arbeitsverzeichnis
CONFIG_FILE = "config.json"


@dataclass
class AppConfig:
    """Anwendungseinstellungen mit sinnvollen Defaults."""

    # ------------------------------------------------------------------ Fenster
    window_geometry: str = "1350x780"
    window_state: str = "normal"          # "normal" | "zoomed"
    paned_positions: list[int] = field(default_factory=list)

    # ----------------------------------------------------- Letzte Parameter
    last_tool_id: str = ""
    last_program_number: str = "1000"
    last_program_name: str = "TEIL_1"
    last_speed: str = "3000"
    last_feed_xy: str = "400"
    last_feed_z: str = "120"
    last_depth: str = "-5"
    last_step: str = "-1"
    last_safety: str = "50"
    last_offset: str = "G54"
    last_snap_grid: str = "0.0"
    last_approach_dist: str = "5.0"
    last_coolant: bool = True
    last_use_comp: bool = False
    last_comp_side: str = "left"
    last_post: str = ""
    last_check_collisions: bool = True

    # ---------------------------------------- Zeichnung / Front-/Seitenansicht
    last_stock_height: str = "20"
    last_drawing_mode: str = "all"        # "top" | "three" | "iso" | "all"

    # --------------------------------------------------------- Letzte Pfade
    last_stl_dir: str = ""
    last_dxf_dir: str = ""
    last_save_dir: str = ""

    # ------------------------------------------------- Werkzeugdatenbank
    tools_db_path: str = "tools.json"

    # ==================================================================
    # Laden / Speichern
    # ==================================================================
    @classmethod
    def load(cls, path: str = CONFIG_FILE) -> "AppConfig":
        """
        Lädt die Config aus einer JSON-Datei.

        - Fehlt die Datei, wird eine neue Instanz mit Defaults zurückgegeben.
        - Bei Fehlern in der Datei werden die Defaults verwendet, damit
          das Programm immer startet.
        - Unbekannte Felder werden ignoriert (robust gegen alte Configs).
        """
        if not os.path.isfile(path):
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[config] Konnte {path} nicht lesen: {exc} – nutze Defaults.")
            return cls()

        if not isinstance(data, dict):
            print(f"[config] {path} hat unerwartetes Format – nutze Defaults.")
            return cls()

        # Nur bekannte Felder übernehmen
        known = set(cls.__dataclass_fields__)
        filtered = {k: v for k, v in data.items() if k in known}
        try:
            return cls(**filtered)
        except TypeError as exc:
            print(f"[config] Feldtyp-Fehler in {path}: {exc} – nutze Defaults.")
            return cls()

    def save(self, path: str = CONFIG_FILE) -> None:
        """
        Schreibt die Config atomar in eine JSON-Datei.

        Es wird zuerst in eine .tmp-Datei geschrieben und dann per
        os.replace() umbenannt – so bleibt die Originaldatei intakt,
        falls der Schreibvorgang mittendrin abbricht.
        """
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as exc:
            print(f"[config] Konnte {path} nicht schreiben: {exc}")

    # ==================================================================
    # Hilfsmethoden
    # ==================================================================
    def get(self, key: str, default: Any = None) -> Any:
        """Sicherer Zugriff auf ein Feld (gibt default zurück, wenn nicht vorhanden)."""
        return getattr(self, key, default)

    def set(self, key: str, value: Any) -> None:
        """Setzt ein Feld, aber nur wenn es existiert."""
        if key in self.__dataclass_fields__:
            setattr(self, key, value)


# ======================================================================
# Schnelltest – nur wenn die Datei direkt ausgeführt wird
# ======================================================================
if __name__ == "__main__":
    cfg = AppConfig.load()
    print("Geladene Config:")
    for k, v in asdict(cfg).items():
        print(f"  {k}: {v!r}")

    print("\nSpeichere Test-Config nach config_test.json …")
    cfg.save("config_test.json")
    print("OK.")