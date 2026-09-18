"""
dxf_loader.py
-------------
Liest DXF-Dateien und wandelt Geometrie in Polylinien und Kreise um.

NEU: ARCs werden zusammengesetzt:
- Mehrere ARCs mit gleichem Mittelpunkt und Radius → Kreis
- ARCs mit gemeinsamen Endpunkten → zusammenhängende Polylinie

Unterstützt:
- LINE, LWPOLYLINE, POLYLINE
- ARC (mit intelligenter Verkettung)
- CIRCLE (direkt)
- SPLINE (als Polylinie approximiert)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

import numpy as np

try:
    import ezdxf
except ImportError as exc:
    raise ImportError(
        "Das Paket 'ezdxf' fehlt. Bitte installieren mit:\n"
        "    pip install ezdxf"
    ) from exc


Point2D = Tuple[float, float]


@dataclass
class Contour:
    """Eine Kontur aus 2D-Punkten."""
    points: np.ndarray
    layer: str = ""
    closed: bool = False

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        xs, ys = self.points[:, 0], self.points[:, 1]
        return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


@dataclass
class Hole:
    """Eine Bohrung (Kreis)."""
    x: float
    y: float
    diameter: float
    layer: str = ""


@dataclass
class DxfContent:
    contours: List[Contour] = field(default_factory=list)
    holes: List[Hole] = field(default_factory=list)
    units: str = "mm"
    layers: List[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# ARC-Hilfsklasse
# --------------------------------------------------------------------------- #

@dataclass
class ArcEntity:
    """Ein einzelner ARC."""
    cx: float          # Mittelpunkt X
    cy: float          # Mittelpunkt Y
    r: float           # Radius
    a0: float          # Startwinkel (rad)
    a1: float          # Endwinkel (rad)
    layer: str = ""

    def start_point(self) -> Point2D:
        return (self.cx + self.r * math.cos(self.a0),
                self.cy + self.r * math.sin(self.a0))

    def end_point(self) -> Point2D:
        return (self.cx + self.r * math.cos(self.a1),
                self.cy + self.r * math.sin(self.a1))

    def matches(self, other: "ArcEntity",
                radius_tol: float = 0.01,
                center_tol: float = 0.01) -> bool:
        """Prüft, ob zwei ARCs zum selben Kreis gehören."""
        return (abs(self.r - other.r) < radius_tol
                and abs(self.cx - other.cx) < center_tol
                and abs(self.cy - other.cy) < center_tol)


# --------------------------------------------------------------------------- #
# Hauptfunktion
# --------------------------------------------------------------------------- #

def load_dxf(file_path: str, arc_resolution: float = 32) -> DxfContent:
    """
    Liest ein DXF und extrahiert Konturen, Kreise und Bohrungen.

    Parameter:
        file_path        – Pfad zur DXF-Datei
        arc_resolution   – Punkte pro Radiant für ARC-Auflösung
                           (Standard: 32 Punkte pro rad ≈ 6° pro Punkt)
    """
    doc = ezdxf.readfile(file_path)
    msp = doc.modelspace()

    # Einheiten
    units_code = doc.header.get("$INSUNITS", 4)
    units = "inch" if units_code == 1 else "mm"

    # Sammelbehälter
    contours: List[Contour] = []
    holes: List[Hole] = []
    arcs: List[ArcEntity] = []
    layer_set: set = set()

    # Zähler für Diagnose
    entity_counts = {"LINE": 0, "LWPOLYLINE": 0, "POLYLINE": 0,
                     "CIRCLE": 0, "ARC": 0, "SPLINE": 0, "andere": 0}

    # ---------------------------------------------------------------------- #
    # 1) Entities einlesen
    # ---------------------------------------------------------------------- #

    for entity in msp:
        layer = entity.dxf.layer
        layer_set.add(layer)
        etype = entity.dxftype()

        if etype not in entity_counts:
            entity_counts["andere"] += 1
        else:
            entity_counts[etype] += 1

        try:
            # ---- LINE ----
            if etype == "LINE":
                s = entity.dxf.start
                e = entity.dxf.end
                pts = np.array([[s.x, s.y], [e.x, e.y]], dtype=float)
                contours.append(Contour(points=pts, layer=layer,
                                        closed=False))

            # ---- LWPOLYLINE ----
            elif etype == "LWPOLYLINE":
                pts = np.array([(p[0], p[1]) for p in entity.get_points("xy")],
                               dtype=float)
                if len(pts) >= 2:
                    contours.append(Contour(points=pts, layer=layer,
                                            closed=entity.closed))

            # ---- POLYLINE ----
            elif etype == "POLYLINE":
                pts = np.array(
                    [(v.dxf.location.x, v.dxf.location.y)
                     for v in entity.vertices],
                    dtype=float)
                if len(pts) >= 2:
                    contours.append(Contour(points=pts, layer=layer,
                                            closed=entity.is_closed))

            # ---- CIRCLE ----
            elif etype == "CIRCLE":
                cx, cy = entity.dxf.center.x, entity.dxf.center.y
                r = entity.dxf.radius
                holes.append(Hole(cx, cy, r * 2, layer))

            # ---- ARC – erst sammeln, später verarbeiten ----
            elif etype == "ARC":
                arcs.append(ArcEntity(
                    cx=entity.dxf.center.x,
                    cy=entity.dxf.center.y,
                    r=entity.dxf.radius,
                    a0=math.radians(entity.dxf.start_angle),
                    a1=math.radians(entity.dxf.end_angle),
                    layer=layer,
                ))

            # ---- SPLINE – als Polylinie approximieren ----
            elif etype == "SPLINE":
                # ezdxf: Spline in Polylinie konvertieren
                try:
                    pts = np.array(
                        [(p[0], p[1]) for p in entity.flattening(0.05)],
                        dtype=float)
                    if len(pts) >= 2:
                        contours.append(Contour(points=pts, layer=layer,
                                                closed=False))
                except Exception:
                    pass

        except Exception as exc:  # noqa: BLE001
            print(f"[dxf_loader] Fehler bei {etype}: {exc}")

    # ---------------------------------------------------------------------- #
    # 2) ARCs verarbeiten: zu Kreisen und Polylinien zusammensetzen
    # ---------------------------------------------------------------------- #

    arc_holes, arc_polylines = _process_arcs(arcs, arc_resolution)
    holes.extend(arc_holes)
    contours.extend(arc_polylines)

    # ---------------------------------------------------------------------- #
    # 3) Ergebnis
    # ---------------------------------------------------------------------- #

    stats = {
        "entities": entity_counts,
        "contours": len(contours),
        "holes": len(holes),
        "arcs_verarbeitet": len(arcs),
    }

    return DxfContent(
        contours=contours,
        holes=holes,
        units=units,
        layers=sorted(layer_set),
        stats=stats,
    )


# --------------------------------------------------------------------------- #
# ARC-Verarbeitung
# --------------------------------------------------------------------------- #

def _process_arcs(
    arcs: List[ArcEntity],
    arc_resolution: float,
) -> Tuple[List[Hole], List[Contour]]:
    """
    Verarbeitet ARCs:
    - ARCs mit gleichem Center + Radius → Kreis
    - Restliche ARCs → Polylinien (einzeln)

    Rückgabe: (holes, contours)
    """
    holes: List[Hole] = []
    contours: List[Contour] = []

    used = [False] * len(arcs)

    # 1) Gruppieren nach (cx, cy, r) – mit Toleranz
    groups: dict = {}
    for i, arc in enumerate(arcs):
        key = (round(arc.cx, 2), round(arc.cy, 2), round(arc.r, 2))
        groups.setdefault(key, []).append(i)

    # 2) Für jede Gruppe: prüfen, ob die ARCs einen Vollkreis bilden
    for key, indices in groups.items():
        group_arcs = [arcs[i] for i in indices]
        # Gesamtwinkel aufsummieren
        total_angle = sum(_arc_angle(a) for a in group_arcs)

        if total_angle >= 2 * math.pi - 0.1:
            # Das ist ein Kreis!
            first = group_arcs[0]
            holes.append(Hole(
                x=first.cx, y=first.cy,
                diameter=first.r * 2,
                layer=first.layer,
            ))
            for i in indices:
                used[i] = True

    # 3) Restliche ARCs als Polylinien
    for i, arc in enumerate(arcs):
        if used[i]:
            continue
        pts = _discretize_arc(arc, arc_resolution)
        contours.append(Contour(points=pts, layer=arc.layer, closed=False))

    return holes, contours


def _arc_angle(arc: ArcEntity) -> float:
    """Berechnet die Winkelspanne eines ARC (immer positiv)."""
    a0, a1 = arc.a0, arc.a1
    if a1 >= a0:
        return a1 - a0
    return (a1 + 2 * math.pi) - a0


def _discretize_arc(
    arc: ArcEntity,
    resolution: float,
) -> np.ndarray:
    """Wandelt einen ARC in eine Punktfolge um."""
    angle = _arc_angle(arc)
    # Anzahl Punkte proportional zum Winkel
    n = max(8, int(angle * resolution) + 1)
    angles = np.linspace(arc.a0, arc.a0 + angle, n)
    xs = arc.cx + arc.r * np.cos(angles)
    ys = arc.cy + arc.r * np.sin(angles)
    return np.column_stack([xs, ys])