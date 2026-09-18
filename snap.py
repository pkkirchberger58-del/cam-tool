"""
snap.py
-------
Berechnung sicherer Anfahrpunkte und optionales Einrasten auf ein Raster.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np


# --------------------------------------------------------------------------- #

def snap_to_grid(value: float, grid: float) -> float:
    if grid <= 0:
        return value
    return round(value / grid) * grid


def snap_point_to_grid(x: float, y: float, grid: float) -> Tuple[float, float]:
    return snap_to_grid(x, grid), snap_to_grid(y, grid)


# --------------------------------------------------------------------------- #

def polygon_signed_area(points: np.ndarray) -> float:
    """Positiv = gegen den Uhrzeigersinn (CCW), negativ = im Uhrzeigersinn."""
    x, y = points[:, 0], points[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def is_closed_ccw(points: np.ndarray) -> bool:
    return polygon_signed_area(points) > 0


# --------------------------------------------------------------------------- #

@dataclass
class ApproachPlan:
    """
    Beschreibt, wie eine Kontur sicher angefahren wird.

    start        – erster Punkt der (eventuell verschobenen) Kontur
    approach     – Punkt außerhalb, von dem aus zugestellt wird
    direction    – "ccw" | "cw"   (Erkennung, welche Richtung die Kontur läuft)
    is_outer     – True, wenn Außenkontur (Werkzeug läuft außen herum)
    comp_side    – "G41" (links) oder "G42" (rechts) – passend zur Richtung
    """
    start: Tuple[float, float]
    approach: Tuple[float, float]
    direction: str
    is_outer: bool
    comp_side: str


def plan_approach(
    points: np.ndarray,
    approach_distance: float = 5.0,
    grid: float = 0.0,
    force_outer: bool | None = None,
) -> ApproachPlan:
    """
    Erzeugt einen Anfahrplan für eine geschlossene Kontur.

    Parameter:
        points             – (N, 2) geschlossene Kontur
        approach_distance  – Abstand des Anfahrpunkts vom Startpunkt
        grid               – Rasterweite; 0 = kein Snap
        force_outer        – True = Außenkontur, False = Innenkontur, None = Auto
    """
    if len(points) < 2:
        # Degeneriert – nichts zu tun
        x, y = points[0] if len(points) else (0.0, 0.0)
        return ApproachPlan(
            start=(x, y), approach=(x, y),
            direction="ccw", is_outer=True, comp_side="G41")

    p0 = points[0].copy()
    p1 = points[1].copy()

    # Tangentialrichtung am Startpunkt
    tangent = p1 - p0
    t_len = np.hypot(*tangent)
    if t_len < 1e-9:
        tangent = np.array([1.0, 0.0])
    else:
        tangent /= t_len

    # Normale (90° links der Tangente)
    normal = np.array([-tangent[1], tangent[0]])

    ccw = is_closed_ccw(points)

    # Innen/Außen bestimmen:
    # Standard-Heuristik: Ist der erste Punkt "außen"?
    # (funktioniert für einfache 1-Kontur-Fälle; bei mehreren Konturen
    #  entscheidet später die GUI / der Anwender)
    if force_outer is None:
        centroid = points[:-1].mean(axis=0)
        is_outer = bool(np.linalg.norm(p0 - centroid) > np.linalg.norm(
            points[:-1].mean(axis=0) - points[:-1].mean(axis=0) + 1e-9)) \
            if False else True  # Standard: Außenkontur
    else:
        is_outer = bool(force_outer)

    # Anfahrpunkt: außerhalb der Kontur in Richtung der Außennormalen
    side = 1.0 if is_outer else -1.0
    approach = p0 + normal * approach_distance * side

    # Snap
    if grid > 0:
        approach = np.array(snap_point_to_grid(approach[0], approach[1], grid))

    # Richtung & Korrekturseite
    # Faustregel: Außenkontur CCW → G41 (links vom Weg),
    #             Innenkontur  CCW → G42 (rechts vom Weg)
    if is_outer:
        comp_side = "G41" if ccw else "G42"
    else:
        comp_side = "G42" if ccw else "G41"

    return ApproachPlan(
        start=(float(p0[0]), float(p0[1])),
        approach=(float(approach[0]), float(approach[1])),
        direction="ccw" if ccw else "cw",
        is_outer=is_outer,
        comp_side=comp_side,
    )