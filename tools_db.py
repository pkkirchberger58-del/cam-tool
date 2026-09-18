"""
tools_db.py
-----------
Verwaltung einer Werkzeugdatenbank in tools.json.

Werkzeugtypen:
- fraeser           (Schaftfräser, Torusfräser, Kugelfräser)
- bohrer            (Spiralbohrer, Zentrierbohrer)
- gewindeschneider  (Maschinengewindebohrer)
- senker            (Kegelsenker, PlanSenker)
- reibahle          (Hand-/Maschinenreibahle)

Die Datei wird beim ersten Start automatisch mit Beispielen angelegt.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional


TOOLS_FILE = "tools.json"

# --------------------------------------------------------------------------- #

# Erlaubte Werkzeugtypen (für Combobox im Editor)
TOOL_TYPES = [
    "fraeser",
    "bohrer",
    "gewindeschneider",
    "senker",
    "reibahle",
]

TOOL_TYPE_LABELS = {
    "fraeser": "Fräser",
    "bohrer": "Bohrer",
    "gewindeschneider": "Gewindeschneider",
    "senker": "Senker",
    "reibahle": "Reibahle",
}

MATERIALS = ["VHM", "HSS", "HSS-E", "DIA", "Sonstige"]
COATINGS = ["unbeschichtet", "TiN", "TiAlN", "TiCN", "AlCrN", "DLC"]


# --------------------------------------------------------------------------- #

@dataclass
class Tool:
    """Ein einzelnes Werkzeug."""
    id: str = ""
    name: str = ""
    type: str = "fraeser"            # einer von TOOL_TYPES
    diameter: float = 6.0
    corner_radius: float = 0.0       # 0 = scharfe Ecke, >0 = Torus, = d/2 = Kugel
    flute_length: float = 20.0
    total_length: float = 60.0
    flutes: int = 2
    material: str = "VHM"
    coating: str = "unbeschichtet"
    rpm_min: int = 1000
    rpm_max: int = 18000
    feed_min: int = 100
    feed_max: int = 1500
    # Typ-spezifisch
    tip_angle: float = 0.0           # Bohrer: 118, 90, ...
    thread_pitch: float = 0.0        # Gewindeschneider: M6 -> 1.0
    comment: str = ""

    # -------------------------------------------------------- Convenience --
    def rpm_default(self) -> int:
        return int((self.rpm_min + self.rpm_max) / 2)

    def feed_default(self) -> int:
        return int((self.feed_min + self.feed_max) / 2)

    def validate(self) -> List[str]:
        """Gibt eine Liste von Fehlermeldungen zurück (leer = OK)."""
        errors: List[str] = []
        if not self.id.strip():
            errors.append("ID darf nicht leer sein.")
        if not self.name.strip():
            errors.append("Name darf nicht leer sein.")
        if self.type not in TOOL_TYPES:
            errors.append(f"Unbekannter Typ: {self.type}")
        if self.diameter <= 0:
            errors.append("Durchmesser muss > 0 sein.")
        if self.rpm_min > self.rpm_max:
            errors.append("Drehzahl min > max.")
        if self.feed_min > self.feed_max:
            errors.append("Vorschub min > max.")
        if self.type == "gewindeschneider" and self.thread_pitch <= 0:
            errors.append("Gewindeschneider braucht eine Steigung > 0.")
        return errors

    @classmethod
    def from_dict(cls, data: dict) -> "Tool":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


# --------------------------------------------------------------------------- #

class ToolDatabase:
    """Lädt und speichert eine Liste von Werkzeugen aus tools.json."""

    def __init__(self, path: str = TOOLS_FILE) -> None:
        self.path = path
        self.tools: List[Tool] = []
        self.load()

    # ---------------------------------------------------------------- Laden --
    def load(self) -> None:
        if not os.path.isfile(self.path):
            self.tools = self._default_tools()
            self.save()
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[tools_db] Konnte {self.path} nicht lesen: {exc}")
            self.tools = self._default_tools()
            return

        raw_tools = data.get("tools", [])
        self.tools = [Tool.from_dict(t) for t in raw_tools]

    # -------------------------------------------------------------- Speichern --
    def save(self) -> None:
        payload = {
            "version": 1,
            "tools": [asdict(t) for t in self.tools],
        }
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as exc:
            print(f"[tools_db] Konnte {self.path} nicht schreiben: {exc}")

    # ----------------------------------------------------------- Zugriff --
    def get(self, tool_id: str) -> Optional[Tool]:
        for t in self.tools:
            if t.id == tool_id:
                return t
        return None

    def find_by_diameter(self, diameter: float,
                         tolerance: float = 0.05,
                         tool_type: Optional[str] = None) -> Optional[Tool]:
        """Findet ein Werkzeug mit passendem Durchmesser (±Toleranz)."""
        for t in self.tools:
            if tool_type and t.type != tool_type:
                continue
            if abs(t.diameter - diameter) <= tolerance:
                return t
        return None

    def add(self, tool: Tool) -> None:
        if self.get(tool.id):
            raise ValueError(f"Werkzeug-ID '{tool.id}' existiert bereits.")
        self.tools.append(tool)

    def replace(self, old_id: str, tool: Tool) -> None:
        for i, t in enumerate(self.tools):
            if t.id == old_id:
                self.tools[i] = tool
                return
        raise ValueError(f"Werkzeug '{old_id}' nicht gefunden.")

    def remove(self, tool_id: str) -> None:
        self.tools = [t for t in self.tools if t.id != tool_id]

    def next_free_id(self, prefix: str = "T") -> str:
        """Erzeugt eine neue, freie ID wie T01, T02, ..."""
        used = {t.id for t in self.tools}
        for i in range(1, 1000):
            candidate = f"{prefix}{i:02d}"
            if candidate not in used:
                return candidate
        return f"{prefix}999"

    # ----------------------------------------------------- Beispieldaten --
    @staticmethod
    def _default_tools() -> List[Tool]:
        return [
            Tool(id="T01", name="Schafffräser Ø6 VHM",
                 type="fraeser", diameter=6.0, corner_radius=0.0,
                 flute_length=20, total_length=60, flutes=3,
                 material="VHM", coating="TiAlN",
                 rpm_min=4000, rpm_max=18000,
                 feed_min=300, feed_max=1500,
                 comment="Standard-Schruppfräser"),
            Tool(id="T02", name="Schafffräser Ø8 VHM",
                 type="fraeser", diameter=8.0, corner_radius=0.0,
                 flute_length=25, total_length=70, flutes=3,
                 material="VHM", coating="TiAlN",
                 rpm_min=3000, rpm_max=15000,
                 feed_min=400, feed_max=1800),
            Tool(id="T03", name="Kugelfräser Ø6 VHM",
                 type="fraeser", diameter=6.0, corner_radius=3.0,
                 flute_length=20, total_length=60, flutes=2,
                 material="VHM", coating="AlCrN",
                 rpm_min=6000, rpm_max=20000,
                 feed_min=300, feed_max=1200),
            Tool(id="T04", name="Bohrer Ø5 HSS",
                 type="bohrer", diameter=5.0,
                 flute_length=40, total_length=80, flutes=2,
                 material="HSS", coating="unbeschichtet",
                 rpm_min=500, rpm_max=3000,
                 feed_min=50, feed_max=300,
                 tip_angle=118.0),
            Tool(id="T05", name="Bohrer Ø8 HSS-Co",
                 type="bohrer", diameter=8.0,
                 flute_length=60, total_length=110, flutes=2,
                 material="HSS-E", coating="TiN",
                 rpm_min=400, rpm_max=2200,
                 feed_min=60, feed_max=350,
                 tip_angle=118.0),
            Tool(id="T06", name="Gewindeschneider M6",
                 type="gewindeschneider", diameter=6.0,
                 flute_length=20, total_length=80, flutes=3,
                 material="HSS-E", coating="TiCN",
                 rpm_min=300, rpm_max=800,
                 feed_min=0, feed_max=0,
                 thread_pitch=1.0),
            Tool(id="T07", name="Kegelsenker 90° Ø10",
                 type="senker", diameter=10.0,
                 flute_length=10, total_length=60, flutes=1,
                 material="HSS", coating="TiN",
                 rpm_min=500, rpm_max=1500,
                 feed_min=50, feed_max=200,
                 tip_angle=90.0),
        ]