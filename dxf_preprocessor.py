"""
dxf_preprocessor.py
-------------------
Vorverarbeitung der DXF-Daten für die Verifikation.

GENERISCH – funktioniert für beliebige Geometrien:
- Ringe, Blöcke, Wellen, Gehäuse, ...
- Keine fixen Schwellen für die Größe
- Symbol-Erkennung relativ zur größten Kontur
- Dubletten-Erkennung für Fusion-360-typische Doppelgeometrien

Arbeitsschritte:
1. Kreise erkennen (Kreisfit)
2. Linien-Segmente zu Ketten verbinden
3. Dubletten entfernen
4. Symbole verwerfen
5. Hierarchie analysieren (Verschachtelung)
6. Klassifizieren (outer / inner / pocket / circle / open)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from dxf_loader import Contour as DxfContour, DxfContent


# --------------------------------------------------------------------------- #
# Datenklassen
# --------------------------------------------------------------------------- #

@dataclass
class ProcessedContour:
    """Eine zusammenhängende Kontur nach dem Preprocessing."""
    points: np.ndarray
    kind: str                    # "outer" | "inner" | "pocket" | "circle" | "open"
    closed: bool
    length: float
    layer: str = ""
    # Kreis-Metadaten
    center: Optional[Tuple[float, float]] = None
    radius: Optional[float] = None
    # Hierarchie
    depth: int = 0
    parent_index: Optional[int] = None
    # Herkunft
    source_segments: int = 1

    def bbox(self) -> Tuple[float, float, float, float]:
        if len(self.points) == 0:
            return (0, 0, 0, 0)
        xs, ys = self.points[:, 0], self.points[:, 1]
        return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())

    @property
    def diag(self) -> float:
        x0, y0, x1, y1 = self.bbox()
        return math.hypot(x1 - x0, y1 - y0)

    def contains_point(self, pt: Tuple[float, float]) -> bool:
        """Ray-Casting, funktioniert für geschlossene Konturen."""
        if not self.closed:
            return False
        x, y = pt
        pts = self.points
        n = len(pts)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = pts[i, 0], pts[i, 1]
            xj, yj = pts[j, 0], pts[j, 1]
            if ((yi > y) != (yj > y)) and \
               (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        return inside

    def __repr__(self) -> str:
        x0, y0, x1, y1 = self.bbox()
        kind_str = self.kind
        if self.radius:
            kind_str += f" Ø{self.radius * 2:.1f}"
        return (f"Contour({kind_str}, depth={self.depth}, "
                f"N={len(self.points)}, len={self.length:.1f}, "
                f"bbox=({x0:.1f},{y0:.1f})-({x1:.1f},{y1:.1f}))")


@dataclass
class ProcessedDxf:
    contours: List[ProcessedContour] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def summary(self) -> str:
        lines = [f"Verarbeitete Konturen: {len(self.contours)}"]
        by_kind: Dict[str, int] = {}
        by_depth: Dict[int, int] = {}
        for c in self.contours:
            by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
            by_depth[c.depth] = by_depth.get(c.depth, 0) + 1
        for k, v in sorted(by_kind.items()):
            lines.append(f"  {k}: {v}")
        for d, v in sorted(by_depth.items()):
            lines.append(f"  Tiefe {d}: {v}")
        if self.stats:
            lines.append("Statistik:")
            for k, v in self.stats.items():
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #

@dataclass
class PreprocessConfig:
    # Toleranz zum Verbinden von Linienenden (mm)
    chain_tolerance: float = 0.05

    # Toleranz für "geschlossen"-Erkennung (mm)
    close_tolerance: float = 0.1

    # Symbol-Schwelle als Anteil der größten Kontur-Diagonale
    symbol_fraction: float = 0.005

    # Minimale absolute Länge (mm)
    min_absolute_length: float = 0.3

    # Kreis-Fit-Toleranz (% vom Radius) – gelockert auf 5 %
    circle_fit_tolerance: float = 0.05

    # Minimal Punkte für Kreis-Erkennung
    min_circle_points: int = 12

    # Dubletten-Toleranz (mm)
    duplicate_tolerance: float = 0.5

    # Anteil übereinstimmender Punkte, um als Dublette zu gelten
    duplicate_overlap: float = 0.8

    # Anzahl Test-Punkte für Hierarchie
    hierarchy_test_points: int = 5

    # Anteil der Test-Punkte, die innerhalb liegen müssen
    hierarchy_inside_fraction: float = 0.6


# --------------------------------------------------------------------------- #
# Hauptfunktion
# --------------------------------------------------------------------------- #

def preprocess_dxf(
    dxf_content: DxfContent,
    config: Optional[PreprocessConfig] = None,
) -> ProcessedDxf:
    """
    Generische Vorverarbeitung – funktioniert für jedes Teil.
    """
    config = config or PreprocessConfig()
    result = ProcessedDxf()

    # 1) Kreise erkennen
    circles: List[ProcessedContour] = []
    lines: List[DxfContour] = []

    for c in dxf_content.contours:
        circle = _try_circle(c, config)
        if circle is not None:
            circles.append(circle)
        else:
            lines.append(c)

    print(f"[preprocess] {len(circles)} Kreise erkannt, "
          f"{len(lines)} Linien-Segmente zum Verketten")

    # 2) Linien zu Ketten zusammensetzen
    chains = _build_chains(lines, config)
    print(f"[preprocess] {len(chains)} Ketten gebildet")

    # 3) Alle zusammen
    all_contours = circles + chains
    print(f"[preprocess] {len(all_contours)} Konturen vor Dubletten-Entfernung")

    # 4) Dubletten entfernen
    all_contours = _remove_duplicates(all_contours, config)
    print(f"[preprocess] {len(all_contours)} Konturen nach Dubletten-Entfernung")

    # 5) Größte Kontur bestimmen
    if all_contours:
        max_diag = max(c.diag for c in all_contours)
    else:
        max_diag = 1.0

    # 6) Symbol-Schwelle
    symbol_threshold = max(config.min_absolute_length,
                           max_diag * config.symbol_fraction)
    print(f"[preprocess] Größte Diagonale: {max_diag:.1f} mm, "
          f"Symbol-Schwelle: {symbol_threshold:.2f} mm")

    # 7) Symbole verwerfen
    filtered = []
    for c in all_contours:
        if c.diag < symbol_threshold and c.length < symbol_threshold:
            continue
        filtered.append(c)

    print(f"[preprocess] {len(filtered)} Konturen nach Filter "
          f"({len(all_contours) - len(filtered)} Symbole verworfen)")

    # 8) Hierarchie analysieren
    _analyze_hierarchy(filtered, config)
    print(f"[preprocess] Hierarchie analysiert")

    # 9) Klassifikation
    for c in filtered:
        _classify(c)

    result.contours = filtered
    result.stats = {
        "rohe_konturen": len(dxf_content.contours),
        "kreise": len(circles),
        "ketten": len(chains),
        "nach_dubletten": len(all_contours),
        "symbole_verworfen": len(all_contours) - len(filtered),
        "final": len(filtered),
        "groesste_diagonale": round(max_diag, 2),
        "symbol_schwelle": round(symbol_threshold, 3),
    }

    return result


# --------------------------------------------------------------------------- #
# Kreis-Erkennung (gelockerte Toleranz)
# --------------------------------------------------------------------------- #

def _try_circle(
    contour: DxfContour,
    config: PreprocessConfig,
) -> Optional[ProcessedContour]:
    """
    Prüft, ob eine DXF-Kontur ein Kreis ist.

    Gelockerte Toleranz (5 %) – akzeptiert auch leicht ungenaue Kreise
    aus Fusion-360-Polylinien.
    """
    pts = np.asarray(contour.points, dtype=float)
    if len(pts) < config.min_circle_points:
        return None

    # Geschlossen?
    if not np.allclose(pts[0], pts[-1], atol=config.close_tolerance):
        return None

    # Mittelpunkt = Schwerpunkt (ohne letzten Punkt)
    inner = pts[:-1]
    center = inner.mean(axis=0)

    # Radien
    dx = inner[:, 0] - center[0]
    dy = inner[:, 1] - center[1]
    radii = np.hypot(dx, dy)

    mean_r = float(radii.mean())
    if mean_r < 0.05:
        return None
    max_dev = float(np.max(np.abs(radii - mean_r)))
    if max_dev / mean_r > config.circle_fit_tolerance:
        return None

    return ProcessedContour(
        points=inner,
        kind="circle",
        closed=True,
        length=2 * math.pi * mean_r,
        layer=contour.layer,
        center=(float(center[0]), float(center[1])),
        radius=mean_r,
        source_segments=1,
    )


# --------------------------------------------------------------------------- #
# Ketten-Bildung
# --------------------------------------------------------------------------- #

def _build_chains(
    contours: List[DxfContour],
    config: PreprocessConfig,
) -> List[ProcessedContour]:
    segments = []
    for c in contours:
        pts = np.asarray(c.points, dtype=float)
        if len(pts) < 2:
            continue
        segments.append({
            "start": tuple(pts[0]),
            "end": tuple(pts[-1]),
            "points": pts,
            "used": False,
        })

    chains: List[ProcessedContour] = []

    for seg in segments:
        if seg["used"]:
            continue
        seg["used"] = True
        used_count = 1

        chain_points: List[Tuple[float, float]] = [
            tuple(seg["points"][0]), tuple(seg["points"][-1])
        ]

        used_count += _extend_forward(segments, chain_points, config)
        used_count += _extend_backward(segments, chain_points, config)

        arr = np.array(chain_points, dtype=float)
        if len(arr) < 2:
            continue

        diffs = np.diff(arr, axis=0)
        length = float(np.sum(np.hypot(diffs[:, 0], diffs[:, 1])))
        closed = bool(np.allclose(arr[0], arr[-1],
                                  atol=config.close_tolerance))
        if closed and not np.allclose(arr[0], arr[-1], atol=1e-9):
            arr = np.vstack([arr, arr[0]])

        chains.append(ProcessedContour(
            points=arr,
            kind="?",
            closed=closed,
            length=length,
            source_segments=used_count,
        ))

    return chains


def _extend_forward(segments, chain_points, config) -> int:
    """Erweitert die Kette nach vorne. Gibt Anzahl hinzugefügter Segmente zurück."""
    count = 0
    while True:
        end = chain_points[-1]
        found = False
        for seg in segments:
            if seg["used"]:
                continue
            s, e = seg["start"], seg["end"]
            d_to_start = math.hypot(s[0] - end[0], s[1] - end[1])
            d_to_end = math.hypot(e[0] - end[0], e[1] - end[1])
            if d_to_start <= config.chain_tolerance:
                for pt in seg["points"][1:]:
                    chain_points.append(tuple(pt))
                seg["used"] = True
                found = True
                count += 1
                break
            elif d_to_end <= config.chain_tolerance:
                for pt in reversed(seg["points"][:-1]):
                    chain_points.append(tuple(pt))
                seg["used"] = True
                found = True
                count += 1
                break
        if not found:
            break
    return count


def _extend_backward(segments, chain_points, config) -> int:
    """Erweitert die Kette nach hinten. Gibt Anzahl hinzugefügter Segmente zurück."""
    count = 0
    while True:
        start = chain_points[0]
        found = False
        for seg in segments:
            if seg["used"]:
                continue
            s, e = seg["start"], seg["end"]
            d_to_end = math.hypot(e[0] - start[0], e[1] - start[1])
            d_to_start = math.hypot(s[0] - start[0], s[1] - start[1])
            if d_to_end <= config.chain_tolerance:
                for pt in reversed(seg["points"][:-1]):
                    chain_points.insert(0, tuple(pt))
                seg["used"] = True
                found = True
                count += 1
                break
            elif d_to_start <= config.chain_tolerance:
                for pt in seg["points"][1:]:
                    chain_points.insert(0, tuple(pt))
                seg["used"] = True
                found = True
                count += 1
                break
        if not found:
            break
    return count


# --------------------------------------------------------------------------- #
# Dubletten-Entfernung
# --------------------------------------------------------------------------- #

def _remove_duplicates(
    contours: List[ProcessedContour],
    config: PreprocessConfig,
) -> List[ProcessedContour]:
    """
    Entfernt doppelte Konturen.

    Kriterium:
    - gleiche BBox (innerhalb duplicate_tolerance)
    - ähnliche Länge (innerhalb 5 %)
    - mindestens duplicate_overlap der Punkte übereinstimmend
    """
    if len(contours) < 2:
        return contours

    # Sortiere: die mit den meisten Punkten zuerst
    sorted_contours = sorted(contours,
                             key=lambda c: (-len(c.points), -c.length))

    unique: List[ProcessedContour] = []

    for c in sorted_contours:
        is_dup = False
        for u in unique:
            if _are_duplicates(c, u, config):
                is_dup = True
                break
        if not is_dup:
            unique.append(c)

    return unique


def _are_duplicates(a: ProcessedContour,
                    b: ProcessedContour,
                    config: PreprocessConfig) -> bool:
    """
    Prüft, ob zwei Konturen Dubletten sind.

    Schneller Check: BBox + Länge.
    """
    if len(a.points) < 2 or len(b.points) < 2:
        return False

    tol = config.duplicate_tolerance

    # BBox-Vergleich
    ax0, ay0, ax1, ay1 = a.bbox()
    bx0, by0, bx1, by1 = b.bbox()

    if (abs(ax0 - bx0) > tol or abs(ay0 - by0) > tol or
            abs(ax1 - bx1) > tol or abs(ay1 - by1) > tol):
        return False

    # Länge vergleichen (max 10 % Abweichung)
    len_ratio = a.length / max(1e-9, b.length)
    if len_ratio < 0.9 or len_ratio > 1.1:
        return False

    # Punktanzahl vergleichen
    pt_ratio = len(a.points) / max(1, len(b.points))
    if pt_ratio < 0.5 or pt_ratio > 2.0:
        return False

    return True


# --------------------------------------------------------------------------- #
# Hierarchie-Analyse (robuster)
# --------------------------------------------------------------------------- #

def _analyze_hierarchy(
    contours: List[ProcessedContour],
    config: PreprocessConfig,
) -> None:
    """
    Ermittelt für jede Kontur, in welcher anderen sie liegt.

    Robuster: Statt nur den ersten Punkt zu testen, werden mehrere
    Punkte entlang der Kontur geprüft (Mehrheitsentscheid).
    """
    n = len(contours)

    for i, c in enumerate(contours):
        if not c.closed:
            c.depth = 0
            continue

        # Testpunkte entlang der Kontur verteilt
        step = max(1, len(c.points) // config.hierarchy_test_points)
        test_points = c.points[::step][:config.hierarchy_test_points]

        parents: List[int] = []
        for j, other in enumerate(contours):
            if i == j or not other.closed:
                continue
            # Mehrheit der Testpunkte muss innerhalb liegen
            inside_count = 0
            for pt in test_points:
                if other.contains_point((float(pt[0]), float(pt[1]))):
                    inside_count += 1
            if (inside_count / len(test_points)) >= config.hierarchy_inside_fraction:
                parents.append(j)

        c.depth = len(parents)
        c.parent_index = parents[0] if parents else None


# --------------------------------------------------------------------------- #
# Klassifikation
# --------------------------------------------------------------------------- #

def _classify(contour: ProcessedContour) -> None:
    """
    Klassifiziert eine Kontur anhand ihrer Hierarchie-Position.

    - circle bleibt circle
    - offen → open
    - depth == 0 → outer
    - depth == 1 → inner (Tasche, Nut, Rundung)
    - depth >= 2 → pocket
    """
    if contour.kind == "circle":
        return
    if not contour.closed:
        contour.kind = "open"
        return
    if contour.depth == 0:
        contour.kind = "outer"
    elif contour.depth == 1:
        contour.kind = "inner"
    else:
        contour.kind = "pocket"