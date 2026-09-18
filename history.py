"""
history.py
----------
Speichert die Historie der Verifikationsläufe in history.json.

Struktur:
    [
      {
        "datum": "2026-09-17T14:32:00",
        "dxf": "test.dxf",
        "gcode": "test.mpf",
        "ergebnis": "OK" | "FEHLER",
        "elemente": 428,
        "fehler": 0,
        "max_abw": 0.008,
        "toleranz": 0.01
      },
      ...
    ]
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List


HISTORY_FILE = "history.json"
MAX_ENTRIES = 50


@dataclass
class HistoryEntry:
    datum: str
    dxf: str
    gcode: str
    ergebnis: str           # "OK" | "FEHLER"
    elemente: int
    fehler: int
    max_abw: float
    toleranz: float

    @classmethod
    def from_dict(cls, data: dict) -> "HistoryEntry":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


class History:
    """Verwaltet die Historie der Prüfungen."""

    def __init__(self, path: str = HISTORY_FILE) -> None:
        self.path = path
        self.entries: List[HistoryEntry] = []
        self.load()

    def load(self) -> None:
        if not os.path.isfile(self.path):
            self.entries = []
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.entries = [HistoryEntry.from_dict(e) for e in data]
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[history] Konnte {self.path} nicht lesen: {exc}")
            self.entries = []

    def save(self) -> None:
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump([asdict(e) for e in self.entries],
                          f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as exc:
            print(f"[history] Konnte {self.path} nicht schreiben: {exc}")

    def add(self, entry: HistoryEntry) -> None:
        self.entries.insert(0, entry)
        if len(self.entries) > MAX_ENTRIES:
            self.entries = self.entries[:MAX_ENTRIES]
        self.save()

    def get_recent(self, n: int = 5) -> List[HistoryEntry]:
        return self.entries[:n]

    @staticmethod
    def now_str() -> str:
        return datetime.now().strftime("%d.%m. %H:%M")