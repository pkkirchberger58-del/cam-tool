"""
drawing_multi.py
----------------
Multi-Page-Bericht für komplexe Werkstücke.

Erzeugt aus DXF-Konturen einen mehrseitigen PDF-Bericht, bei dem
jede Ansicht eine eigene Seite mit optimalem Maßstab erhält.

Vorteil bei komplexen Zeichnungen:
- Keine Überlappung von Bemaßungen
- Große, lesbare Darstellung
- Maßstabsangabe pro Seite (1:2,5 / 1:5 / …)
- Zusätzliche Seiten für Bohrungsliste und Details

Seitenaufbau:
    1. Titelseite
    2. Draufsicht
    3. Frontansicht
    4. Seitenansicht
    5. Isometrie
    6. Bohrungsliste
    7+. Detail-Seiten (optional, bei großen Teilen)
"""

from __future__ import annotations

import datetime
import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
from matplotlib.backends.backend_pdf import PdfPages


# --------------------------------------------------------------------------- #
# Papierformate (in mm, Querformat)
# --------------------------------------------------------------------------- #

PAGE_SIZES = {
    "A1": (841, 594),
    "A2": (594, 420),
    "A3": (420, 297),
    "A4": (297, 210),
}

# Umrechnung mm → Zoll (matplotlib rechnet in Zoll)
MM_TO_INCH = 1 / 25.4

# Rand (oben, unten, links, rechts) in mm
PAGE_MARGIN_MM = 20

# Bereich für den Titelblock unten (in mm)
TITLE_BLOCK_HEIGHT_MM = 25



# --------------------------------------------------------------------------- #
# Konfiguration
# --------------------------------------------------------------------------- #

@dataclass
class MultiPageConfig:
    """Konfiguration für den Multi-Page-Bericht."""

    page_format: str = "A3"
    orientation: str = "landscape"

    include_cover: bool = True
    include_top: bool = True
    include_front: bool = True
    include_side: bool = True
    include_iso: bool = True
    include_hole_list: bool = True

    # Detail-Seiten
    auto_detail: bool = False
    detail_threshold_mm: float = 500
    include_detail_manual: bool = False

    # Skalierung
    scale_mode: str = "auto"
    fixed_scale: float = 1.0

    # Z-Überhöhung
    z_scale_factor: float = 1.0    # 1.0 = keine, 3.0 = 3× überhöht


# --------------------------------------------------------------------------- #
# Datenklassen (Wiederverwendung)
# --------------------------------------------------------------------------- #

@dataclass
class DrawingParams:
    """Zusatzinfos für den Titelblock."""
    program_name: str = "TEIL"
    program_number: str = "1000"
    tool_name: str = ""
    tool_diameter: float = 0.0
    total_depth: float = 0.0
    stock_height: float = 20.0
    post_name: str = ""
    units: str = "mm"


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #

def _fmt(v: float, decimals: int = 2) -> str:
    s = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _get_page_size_mm(fmt: str, orientation: str) -> Tuple[float, float]:
    """Gibt die Papiergröße in mm zurück (Breite, Höhe)."""
    w, h = PAGE_SIZES.get(fmt.upper(), PAGE_SIZES["A3"])
    if orientation == "portrait":
        return h, w
    return w, h


def _get_available_area_mm(fmt: str, orientation: str) -> Tuple[float, float]:
    """Verfügbare Zeichenfläche (ohne Ränder und Titelblock)."""
    w, h = _get_page_size_mm(fmt, orientation)
    avail_w = w - 2 * PAGE_MARGIN_MM
    avail_h = h - 2 * PAGE_MARGIN_MM - TITLE_BLOCK_HEIGHT_MM
    return avail_w, avail_h


def _compute_standard_scale(bbox_w: float, bbox_h: float,
                             avail_w: float, avail_h: float) -> float:
    """
    Berechnet den optimalen Standard-Maßstab.

    Rückgabe: Faktor (z. B. 2.5 bedeutet Maßstab 1:2,5)
    """
    if bbox_w <= 0 or bbox_h <= 0:
        return 1.0

    # Maximale Skalierung (fit-to-page)
    scale_w = avail_w / bbox_w
    scale_h = avail_h / bbox_h
    max_scale = min(scale_w, scale_h) * 0.9  # 10 % Rand

    # Bei Vergrößerung (Maßstab 2:1, 5:1): möglich, aber selten
    # Bei Verkleinerung: 1:2, 1:2.5, 1:5, 1:10, ...

    # Wenn Bild kleiner als Fläche → 1:1 verwenden
    if max_scale >= 1.0:
        return 1.0

    # Sonst: Standard-Maßstäbe durchprobieren
    # 1:1.25, 1:1.5, 1:2, 1:2.5, 1:5, 1:10, 1:20, 1:25, 1:50, 1:100
    standard = [1.0, 1.25, 1.5, 2.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0]

    for s in standard:
        if 1.0 / s <= max_scale:
            return s

    return 100.0


def _format_scale(scale: float) -> str:
    """Formatiert einen Maßstab als String (z. B. '1:2,5')."""
    if scale == 1.0:
        return "1:1"
    if scale < 1.0:
        # Vergrößerung: 2:1, 5:1
        return f"{_fmt(1.0 / scale, 1)}:1".replace(".", ",")
    # Verkleinerung: 1:2, 1:2,5
    return f"1:{_fmt(scale, 1).replace('.', ',')}"


# --------------------------------------------------------------------------- #
# Titelblock
# --------------------------------------------------------------------------- #

def _draw_title_block(ax, params: DrawingParams,
                      page_num: int, page_total: int,
                      view_name: str, scale: float,
                      page_width_mm: float) -> None:
    """Zeichnet den Titelblock am unteren Rand."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Rahmen
    ax.add_patch(Rectangle((0.01, 0.05), 0.98, 0.9,
                           fill=False, edgecolor="#1f4e79",
                           linewidth=1.0,
                           transform=ax.transAxes))

    # Linke Spalte
    lines_left = [
        ("Programm", f"{params.program_number} – {params.program_name}"),
        ("Werkzeug", f"{params.tool_name}  Ø{_fmt(params.tool_diameter)} {params.units}"),
    ]
    y = 0.75
    for label, value in lines_left:
        ax.text(0.03, y, f"{label}:", fontsize=7,
                color="#555", transform=ax.transAxes)
        ax.text(0.13, y, value, fontsize=7,
                color="#000", fontweight="bold", transform=ax.transAxes)
        y -= 0.22

    # Mittlere Spalte
    lines_mid = [
        ("Ansicht", view_name),
        ("Maßstab", _format_scale(scale)),
    ]
    y = 0.75
    for label, value in lines_mid:
        ax.text(0.42, y, f"{label}:", fontsize=7,
                color="#555", transform=ax.transAxes)
        ax.text(0.52, y, value, fontsize=7,
                color="#000", fontweight="bold", transform=ax.transAxes)
        y -= 0.22

    # Rechte Spalte
    lines_right = [
        ("Datum", datetime.datetime.now().strftime("%d.%m.%Y %H:%M")),
        ("Blatt", f"{page_num} / {page_total}"),
    ]
    y = 0.75
    for label, value in lines_right:
        ax.text(0.72, y, f"{label}:", fontsize=7,
                color="#555", transform=ax.transAxes)
        ax.text(0.81, y, value, fontsize=7,
                color="#000", fontweight="bold", transform=ax.transAxes)
        y -= 0.22


# --------------------------------------------------------------------------- #
# Einzelne Seiten
# --------------------------------------------------------------------------- #

def _draw_cover_page(fig, params: DrawingParams,
                     n_contours: int, n_holes: int,
                     config: MultiPageConfig,
                     page_total: int) -> None:
    """Seite 1: Titelseite mit Zusammenfassung."""
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Titel
    ax.text(0.5, 0.88, "Verifikations-Bericht",
            fontsize=28, fontweight="bold",
            ha="center", va="center",
            color="#1f4e79", transform=ax.transAxes)

    ax.text(0.5, 0.82, "CAM-Prüfung gegen CAD-Zeichnung",
            fontsize=14, ha="center", va="center",
            color="#666", transform=ax.transAxes)

    # Trennlinie
    ax.plot([0.2, 0.8], [0.78, 0.78],
            color="#1f4e79", linewidth=1.0,
            transform=ax.transAxes)

    # Info-Block
    y = 0.68
    info_items = [
        ("Programm",   f"{params.program_number} – {params.program_name}"),
        ("Werkzeug",   f"{params.tool_name}"),
        ("Ø Werkzeug", f"{_fmt(params.tool_diameter)} {params.units}"),
        ("Steuerung",  params.post_name),
        ("Tiefe",      f"{_fmt(abs(params.total_depth))} {params.units}"),
        ("Rohteil",    f"{_fmt(params.stock_height)} {params.units}"),
    ]
    for label, value in info_items:
        ax.text(0.30, y, f"{label}:", fontsize=12,
                ha="right", va="center", color="#555",
                transform=ax.transAxes)
        ax.text(0.32, y, value, fontsize=12,
                ha="left", va="center", color="#000",
                fontweight="bold", transform=ax.transAxes)
        y -= 0.05

    # Zeichnungs-Statistik
    y = 0.35
    ax.plot([0.2, 0.8], [0.38, 0.38],
            color="#cccccc", linewidth=0.8,
            transform=ax.transAxes)

    stats = [
        ("Konturen",  f"{n_contours}"),
        ("Kreise/Bohrungen", f"{n_holes}"),
    ]
    for label, value in stats:
        ax.text(0.30, y, f"{label}:", fontsize=11,
                ha="right", va="center", color="#555",
                transform=ax.transAxes)
        ax.text(0.32, y, value, fontsize=11,
                ha="left", va="center", color="#000",
                fontweight="bold", transform=ax.transAxes)
        y -= 0.05

    # Datum
    ax.text(0.5, 0.12,
            f"Erstellt am {datetime.datetime.now().strftime('%d.%m.%Y um %H:%M Uhr')}",
            fontsize=10, ha="center", va="center",
            color="#666", transform=ax.transAxes)

    # Blatt-Nummer
    ax.text(0.5, 0.06, f"Blatt 1 / {page_total}",
            fontsize=9, ha="center", va="center",
            color="#999", style="italic", transform=ax.transAxes)


def _draw_top_view_page(fig, contours, holes,
                         params: DrawingParams, config: MultiPageConfig,
                         page_num: int, page_total: int) -> None:
    """Seite: Draufsicht (bemaßt)."""
    ax = fig.add_axes([0.05, 0.10, 0.90, 0.82])

    # Alle Punkte
    all_x, all_y = [], []
    for c in contours:
        ax.plot(c[:, 0], c[:, 1], "-", color="#1f4e79", linewidth=1.4)
        all_x.extend(c[:, 0].tolist())
        all_y.extend(c[:, 1].tolist())

    for x, y, d in holes:
        circ = Circle((x, y), radius=d / 2, fill=False,
                      edgecolor="#c0392b", linewidth=1.2)
        ax.add_patch(circ)
        ax.text(x, y, f"Ø{_fmt(d)}", ha="center", va="center",
                fontsize=8, color="#c0392b", fontweight="bold",
                bbox=dict(facecolor="white", edgecolor="none",
                          alpha=0.8, pad=0.8))
        all_x += [x - d / 2, x + d / 2]
        all_y += [y - d / 2, y + d / 2]

    if not all_x:
        ax.text(0.5, 0.5, "Keine Geometrie", ha="center", va="center")
        return

    xmin, xmax = min(all_x), max(all_x)
    ymin, ymax = min(all_y), max(all_y)
    w, h = xmax - xmin, ymax - ymin

    # Maßstab berechnen
    avail_w, avail_h = _get_available_area_mm(config.page_format,
                                              config.orientation)
    scale = _compute_standard_scale(w, h, avail_w, avail_h)

    # Bemaßung
    pad = max(w, h) * 0.08
    from matplotlib.patches import FancyArrowPatch
    # Breite unten
    ax.annotate("", xy=(xmin, ymin - pad), xytext=(xmax, ymin - pad),
                arrowprops=dict(arrowstyle="<->", color="#0066cc", lw=1.2))
    ax.text((xmin + xmax) / 2, ymin - pad * 0.6,
            f"{_fmt(w)} {params.units}", ha="center", va="top",
            color="#0066cc", fontsize=10)
    # Höhe links
    ax.annotate("", xy=(xmin - pad, ymin), xytext=(xmin - pad, ymax),
                arrowprops=dict(arrowstyle="<->", color="#0066cc", lw=1.2))
    ax.text(xmin - pad * 0.6, (ymin + ymax) / 2,
            f"{_fmt(h)} {params.units}", ha="right", va="center",
            color="#0066cc", fontsize=10, rotation=90)

    # Skalierung
    margin = max(w, h) * 0.15
    ax.set_xlim(xmin - margin, xmax + margin)
    ax.set_ylim(ymin - margin, ymax + margin)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.5)
    ax.set_xlabel(f"X ({params.units})", fontsize=9)
    ax.set_ylabel(f"Y ({params.units})", fontsize=9)
    ax.set_title("Draufsicht", fontsize=14, fontweight="bold", pad=12)

    # Titelblock
    ax_tb = fig.add_axes([0.05, 0.01, 0.90, 0.07])
    _draw_title_block(ax_tb, params, page_num, page_total,
                      "Draufsicht", scale,
                      _get_page_size_mm(config.page_format,
                                        config.orientation)[0])


def _draw_front_view_page(fig, contours, holes,
                           params: DrawingParams, config: MultiPageConfig,
                           page_num: int, page_total: int) -> None:
    """Seite: Frontansicht (XZ) mit optionaler Z-Überhöhung."""
    ax = fig.add_axes([0.05, 0.10, 0.90, 0.82])

    all_x = []
    for c in contours:
        all_x.extend(c[:, 0].tolist())
    for x, y, d in holes:
        all_x += [x - d / 2, x + d / 2]

    if not all_x:
        return

    xmin, xmax = min(all_x), max(all_x)
    height_real = params.stock_height if params.stock_height > 0 else 20.0

    # Z-Überhöhung NUR für die Darstellung
    z_factor = config.z_scale_factor
    height_display = height_real * z_factor

    # Rohteil-Umriss
    ax.add_patch(Rectangle((xmin, 0), xmax - xmin, height_display,
                           fill=False, edgecolor="#1f4e79",
                           linewidth=1.5))

    # Bohrungen als gestrichelte Linien (mit überhöhtem Z)
    for x, y, d in holes:
        z_depth = abs(params.total_depth)
        z_bot = max(0, height_real - z_depth) * z_factor
        ax.plot([x - d / 2, x - d / 2], [height_display, z_bot],
                color="#c0392b", lw=0.9, linestyle="--")
        ax.plot([x + d / 2, x + d / 2], [height_display, z_bot],
                color="#c0392b", lw=0.9, linestyle="--")

    # Bemaßung
    pad = max(xmax - xmin, height_display) * 0.12
    ax.annotate("", xy=(xmin, -pad * 0.6), xytext=(xmax, -pad * 0.6),
                arrowprops=dict(arrowstyle="<->", color="#0066cc", lw=1.2))
    ax.text((xmin + xmax) / 2, -pad * 0.8,
            f"{_fmt(xmax - xmin)} {params.units}",
            ha="center", va="top", color="#0066cc", fontsize=10)

    # Höhen-Bemaßung mit Hinweis auf Überhöhung
    z_label = f"{_fmt(height_real)} {params.units}"
    if z_factor > 1.0:
        z_label += f" (Z {z_factor:.0f}×)"

    ax.annotate("", xy=(xmin - pad * 0.6, 0),
                xytext=(xmin - pad * 0.6, height_display),
                arrowprops=dict(arrowstyle="<->", color="#0066cc", lw=1.2))
    ax.text(xmin - pad * 0.8, height_display / 2,
            z_label,
            ha="right", va="center", color="#0066cc",
            fontsize=10, rotation=90)

    margin = max(xmax - xmin, height_display) * 0.2
    ax.set_xlim(xmin - margin, xmax + margin)
    ax.set_ylim(-margin, height_display + margin)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.5)
    ax.set_xlabel(f"X ({params.units})", fontsize=9)
    ax.set_ylabel(f"Z ({params.units})", fontsize=9)
    ax.set_title("Frontansicht", fontsize=14, fontweight="bold", pad=12)

    # Maßstab
    avail_w, avail_h = _get_available_area_mm(config.page_format,
                                              config.orientation)
    scale = _compute_standard_scale(xmax - xmin, height_display,
                                     avail_w, avail_h)

    ax_tb = fig.add_axes([0.05, 0.01, 0.90, 0.07])
    _draw_title_block(ax_tb, params, page_num, page_total,
                      "Frontansicht", scale,
                      _get_page_size_mm(config.page_format,
                                        config.orientation)[0])

def _draw_detail_view_page(fig, contours, holes,
                            params: DrawingParams, config: MultiPageConfig,
                            page_num: int, page_total: int,
                            x_range: Tuple[float, float],
                            label: str) -> None:
    """Seite: Detail-Ausschnitt (linke oder rechte Hälfte)."""
    ax = fig.add_axes([0.05, 0.10, 0.90, 0.82])

    xmin_filter, xmax_filter = x_range

    all_x, all_y = [], []
    for c in contours:
        # Nur Punkte im X-Bereich zeichnen
        mask = (c[:, 0] >= xmin_filter) & (c[:, 0] <= xmax_filter)
        if np.any(mask):
            ax.plot(c[mask, 0], c[mask, 1], "-",
                    color="#1f4e79", linewidth=1.4)
            all_x.extend(c[mask, 0].tolist())
            all_y.extend(c[mask, 1].tolist())

    for x, y, d in holes:
        if xmin_filter <= x <= xmax_filter:
            circ = Circle((x, y), radius=d / 2, fill=False,
                          edgecolor="#c0392b", linewidth=1.2)
            ax.add_patch(circ)
            ax.text(x, y, f"Ø{_fmt(d)}", ha="center", va="center",
                    fontsize=8, color="#c0392b", fontweight="bold",
                    bbox=dict(facecolor="white", edgecolor="none",
                              alpha=0.8, pad=0.8))
            all_x += [x - d / 2, x + d / 2]
            all_y += [y - d / 2, y + d / 2]

    if not all_x:
        return

    x_disp_min, x_disp_max = min(all_x), max(all_x)
    y_disp_min, y_disp_max = min(all_y), max(all_y)

    # Skalierung
    w = x_disp_max - x_disp_min
    h = y_disp_max - y_disp_min
    avail_w, avail_h = _get_available_area_mm(config.page_format,
                                              config.orientation)
    scale = _compute_standard_scale(w, h, avail_w, avail_h)

    # Bemaßung
    pad = max(w, h) * 0.08
    ax.annotate("", xy=(x_disp_min, y_disp_min - pad),
                xytext=(x_disp_max, y_disp_min - pad),
                arrowprops=dict(arrowstyle="<->", color="#0066cc", lw=1.2))
    ax.text((x_disp_min + x_disp_max) / 2, y_disp_min - pad * 0.6,
            f"{_fmt(w)} {params.units}",
            ha="center", va="top", color="#0066cc", fontsize=10)

    ax.annotate("", xy=(x_disp_min - pad, y_disp_min),
                xytext=(x_disp_min - pad, y_disp_max),
                arrowprops=dict(arrowstyle="<->", color="#0066cc", lw=1.2))
    ax.text(x_disp_min - pad * 0.6, (y_disp_min + y_disp_max) / 2,
            f"{_fmt(h)} {params.units}",
            ha="right", va="center", color="#0066cc",
            fontsize=10, rotation=90)

    margin = max(w, h) * 0.15
    ax.set_xlim(x_disp_min - margin, x_disp_max + margin)
    ax.set_ylim(y_disp_min - margin, y_disp_max + margin)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.5)
    ax.set_xlabel(f"X ({params.units})", fontsize=9)
    ax.set_ylabel(f"Y ({params.units})", fontsize=9)
    ax.set_title(label, fontsize=14, fontweight="bold", pad=12)

    ax_tb = fig.add_axes([0.05, 0.01, 0.90, 0.07])
    _draw_title_block(ax_tb, params, page_num, page_total,
                      label, scale,
                      _get_page_size_mm(config.page_format,
                                        config.orientation)[0])


def _draw_side_view_page(fig, contours, holes,
                          params: DrawingParams, config: MultiPageConfig,
                          page_num: int, page_total: int) -> None:
    """Seite: Seitenansicht (YZ) mit optionaler Z-Überhöhung."""
    ax = fig.add_axes([0.05, 0.10, 0.90, 0.82])

    all_y = []
    for c in contours:
        all_y.extend(c[:, 1].tolist())
    for x, y, d in holes:
        all_y += [y - d / 2, y + d / 2]

    if not all_y:
        return

    ymin, ymax = min(all_y), max(all_y)
    height_real = params.stock_height if params.stock_height > 0 else 20.0

    # Z-Überhöhung NUR für die Darstellung
    z_factor = config.z_scale_factor
    height_display = height_real * z_factor

    ax.add_patch(Rectangle((ymin, 0), ymax - ymin, height_display,
                           fill=False, edgecolor="#1f4e79",
                           linewidth=1.5))

    for x, y, d in holes:
        z_depth = abs(params.total_depth)
        z_bot = max(0, height_real - z_depth) * z_factor
        ax.plot([y - d / 2, y - d / 2], [height_display, z_bot],
                color="#c0392b", lw=0.9, linestyle="--")
        ax.plot([y + d / 2, y + d / 2], [height_display, z_bot],
                color="#c0392b", lw=0.9, linestyle="--")

    pad = max(ymax - ymin, height_display) * 0.12
    ax.annotate("", xy=(ymin, -pad * 0.6), xytext=(ymax, -pad * 0.6),
                arrowprops=dict(arrowstyle="<->", color="#0066cc", lw=1.2))
    ax.text((ymin + ymax) / 2, -pad * 0.8,
            f"{_fmt(ymax - ymin)} {params.units}",
            ha="center", va="top", color="#0066cc", fontsize=10)

    # Höhen-Bemaßung mit Überhöhungs-Hinweis
    z_label = f"{_fmt(height_real)} {params.units}"
    if z_factor > 1.0:
        z_label += f" (Z {z_factor:.0f}×)"

    ax.annotate("", xy=(ymin - pad * 0.6, 0),
                xytext=(ymin - pad * 0.6, height_display),
                arrowprops=dict(arrowstyle="<->", color="#0066cc", lw=1.2))
    ax.text(ymin - pad * 0.8, height_display / 2,
            z_label,
            ha="right", va="center", color="#0066cc",
            fontsize=10, rotation=90)

    margin = max(ymax - ymin, height_display) * 0.2
    ax.set_xlim(ymin - margin, ymax + margin)
    ax.set_ylim(-margin, height_display + margin)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.5)
    ax.set_xlabel(f"Y ({params.units})", fontsize=9)
    ax.set_ylabel(f"Z ({params.units})", fontsize=9)
    ax.set_title("Seitenansicht", fontsize=14, fontweight="bold", pad=12)

    avail_w, avail_h = _get_available_area_mm(config.page_format,
                                              config.orientation)
    scale = _compute_standard_scale(ymax - ymin, height_display,
                                     avail_w, avail_h)

    ax_tb = fig.add_axes([0.05, 0.01, 0.90, 0.07])
    _draw_title_block(ax_tb, params, page_num, page_total,
                      "Seitenansicht", scale,
                      _get_page_size_mm(config.page_format,
                                        config.orientation)[0])


def _draw_iso_view_page(fig, contours, holes,
                         params: DrawingParams, config: MultiPageConfig,
                         page_num: int, page_total: int) -> None:
    """Seite: Isometrische 3D-Ansicht."""
    ax = fig.add_axes([0.10, 0.10, 0.80, 0.80], projection="3d")

    height = params.stock_height if params.stock_height > 0 else 20.0

    all_x, all_y = [], []
    for c in contours:
        all_x.extend(c[:, 0].tolist())
        all_y.extend(c[:, 1].tolist())
    for x, y, d in holes:
        all_x += [x - d / 2, x + d / 2]
        all_y += [y - d / 2, y + d / 2]

    if not all_x or not all_y:
        return

    xmin, xmax = min(all_x), max(all_x)
    ymin, ymax = min(all_y), max(all_y)

    # Box-Kanten
    corners = [
        (xmin, ymin, 0), (xmax, ymin, 0), (xmax, ymax, 0), (xmin, ymax, 0),
        (xmin, ymin, height), (xmax, ymin, height),
        (xmax, ymax, height), (xmin, ymax, height),
    ]
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    for i, j in edges:
        ax.plot([corners[i][0], corners[j][0]],
                [corners[i][1], corners[j][1]],
                [corners[i][2], corners[j][2]],
                color="#1f4e79", lw=0.8)

    # Konturen oben
    for c in contours:
        ax.plot(c[:, 0], c[:, 1], np.full(len(c), height),
                color="#3a7bd5", lw=1.0)

    # Bohrungen
    for x, y, d in holes:
        z_bot = max(0, height - abs(params.total_depth))
        ax.plot([x, x], [y, y], [height, z_bot],
                color="#c0392b", lw=1.0, linestyle="--")
        t = np.linspace(0, 2 * np.pi, 40)
        cx = x + (d / 2) * np.cos(t)
        cy = y + (d / 2) * np.sin(t)
        cz = np.full_like(cx, height)
        ax.plot(cx, cy, cz, color="#c0392b", lw=0.9)

    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_zlim(0, height)
    ax.set_box_aspect((xmax - xmin, ymax - ymin, height))
    ax.view_init(elev=25, azim=-55)
    ax.set_xlabel(f"X ({params.units})", fontsize=8)
    ax.set_ylabel(f"Y ({params.units})", fontsize=8)
    ax.set_zlabel(f"Z ({params.units})", fontsize=8)
    ax.set_title("Isometrie", fontsize=14, fontweight="bold", pad=12)

    ax_tb = fig.add_axes([0.05, 0.01, 0.90, 0.07])
    _draw_title_block(ax_tb, params, page_num, page_total,
                      "Isometrie", 1.0,
                      _get_page_size_mm(config.page_format,
                                        config.orientation)[0])


def _draw_hole_list_page(fig, holes,
                          params: DrawingParams, config: MultiPageConfig,
                          page_num: int, page_total: int,
                          subpage: int = 1,
                          subpage_total: int = 1) -> None:
    """Seite: Bohrungsliste (Tabelle), optional auf mehrere Seiten verteilt."""
    ax = fig.add_axes([0.05, 0.10, 0.90, 0.82])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Titel mit Subpage-Nummer
    title = "Bohrungsliste"
    if subpage_total > 1:
        title += f"  ({subpage} / {subpage_total})"

    ax.text(0.5, 0.97, title,
            fontsize=16, fontweight="bold",
            ha="center", va="top",
            color="#1f4e79", transform=ax.transAxes)

    if not holes:
        ax.text(0.5, 0.5, "Keine Bohrungen vorhanden",
                fontsize=12, ha="center", va="center",
                color="#999", transform=ax.transAxes)
        # Titelblock trotzdem
        ax_tb = fig.add_axes([0.05, 0.01, 0.90, 0.07])
        _draw_title_block(ax_tb, params, page_num, page_total,
                          "Bohrungsliste", 1.0,
                          _get_page_size_mm(config.page_format,
                                            config.orientation)[0])
        return

    # Tabellenkopf
    y = 0.88
    col_x = [0.05, 0.18, 0.42, 0.62, 0.82]

    headers = ["Nr.", "Durchmesser", "Position X", "Position Y", "LKR"]
    for x, h in zip(col_x, headers):
        ax.text(x, y, h, fontsize=10, fontweight="bold",
                ha="left", va="center",
                color="#1f4e79", transform=ax.transAxes)

    y -= 0.03
    ax.plot([0.03, 0.97], [y, y], color="#1f4e79",
            linewidth=0.8, transform=ax.transAxes)
    y -= 0.02

    # Zeilen
    # Nach Durchmesser und dann LKR sortieren
    sorted_holes = sorted(holes, key=lambda h: (round(h[2], 1),
                                                 math.hypot(h[0], h[1])))

    for i, (x, y_pos, d) in enumerate(sorted_holes, 1):
        if y < 0.04:
            # Kein Platz mehr – sollte nicht passieren, wenn
            # die Seitenaufteilung korrekt arbeitet
            ax.text(0.5, y, "… weitere Bohrungen auf nächster Seite",
                    fontsize=9, ha="center", va="center",
                    color="#999", style="italic",
                    transform=ax.transAxes)
            break

        lkr = math.hypot(x, y_pos) * 2
        global_nr = (subpage - 1) * 35 + i

        ax.text(col_x[0], y, f"{global_nr}",
                fontsize=9, ha="left", va="center",
                color="#000", transform=ax.transAxes)
        ax.text(col_x[1], y, f"Ø{_fmt(d)} mm",
                fontsize=9, ha="left", va="center",
                color="#000", transform=ax.transAxes)
        ax.text(col_x[2], y, f"{_fmt(x)} mm",
                fontsize=9, ha="left", va="center",
                color="#000", transform=ax.transAxes)
        ax.text(col_x[3], y, f"{_fmt(y_pos)} mm",
                fontsize=9, ha="left", va="center",
                color="#000", transform=ax.transAxes)
        ax.text(col_x[4], y,
                f"{_fmt(lkr)} mm" if lkr > 1 else "zentral",
                fontsize=9, ha="left", va="center",
                color="#000", transform=ax.transAxes)

        y -= 0.021

    # Titelblock
    ax_tb = fig.add_axes([0.05, 0.01, 0.90, 0.07])
    _draw_title_block(ax_tb, params, page_num, page_total,
                      "Bohrungsliste", 1.0,
                      _get_page_size_mm(config.page_format,
                                        config.orientation)[0])


# --------------------------------------------------------------------------- #
# Hauptfunktion
# --------------------------------------------------------------------------- #

def create_multipage_drawing(
    contours: List[np.ndarray],
    holes: List[Tuple[float, float, float]],
    output_path: str,
    params: Optional[DrawingParams] = None,
    config: Optional[MultiPageConfig] = None,
    dpi: int = 150,
) -> str:
    """
    Erzeugt einen mehrseitigen PDF-Bericht.

    Parameter:
        contours    – Liste von (N, 2) Punktfolgen
        holes       – Liste von (x, y, diameter)
        output_path – Ziel-Pfad (.pdf)
        params      – DrawingParams für Titelblock
        config      – MultiPageConfig
        dpi         – Auflösung

    Rückgabe: Pfad der erzeugten PDF.
    """
    params = params or DrawingParams()
    config = config or MultiPageConfig()

    # Seitengröße in Zoll
    page_w_mm, page_h_mm = _get_page_size_mm(config.page_format,
                                             config.orientation)
    page_w_in = page_w_mm * MM_TO_INCH
    page_h_in = page_h_mm * MM_TO_INCH

    # Welche Seiten werden erzeugt?
    pages = []
    if config.include_cover:
        pages.append("cover")
    if config.include_top:
        pages.append("top")
    if config.include_front:
        pages.append("front")
    if config.include_side:
        pages.append("side")
    if config.include_iso:
        pages.append("iso")
    if config.include_hole_list and holes:
        # Bohrungsliste auf mehrere Seiten aufteilen
        holes_per_page = 35
        n_hole_pages = (len(holes) + holes_per_page - 1) // holes_per_page
        for i in range(n_hole_pages):
            pages.append(f"holes_{i}")

    # Detail-Seiten bei großen Teilen?
    if config.auto_detail or config.include_detail_manual:
        all_x, all_y = [], []
        for c in contours:
            all_x.extend(c[:, 0].tolist())
            all_y.extend(c[:, 1].tolist())
        if all_x and all_y:
            size = max(max(all_x) - min(all_x),
                       max(all_y) - min(all_y))
            if size > config.detail_threshold_mm:
                pages.append("detail_left")
                pages.append("detail_right")

    page_total = len(pages)


    # PDF erzeugen
    with PdfPages(output_path) as pdf:
        for page_num, page_type in enumerate(pages, 1):
            fig = plt.figure(figsize=(page_w_in, page_h_in), dpi=dpi)
            fig.patch.set_facecolor("white")

            if page_type == "cover":
                _draw_cover_page(fig, params, len(contours), len(holes),
                                 config, page_total)
            elif page_type == "top":
                _draw_top_view_page(fig, contours, holes, params,
                                    config, page_num, page_total)
            elif page_type == "front":
                _draw_front_view_page(fig, contours, holes, params,
                                      config, page_num, page_total)
            elif page_type == "side":
                _draw_side_view_page(fig, contours, holes, params,
                                     config, page_num, page_total)
            elif page_type == "iso":
                _draw_iso_view_page(fig, contours, holes, params,
                                    config, page_num, page_total)
            elif page_type.startswith("holes_"):
                page_idx = int(page_type.split("_")[1])
                start = page_idx * 35
                end = start + 35
                _draw_hole_list_page(fig, holes[start:end], params,
                                     config, page_num, page_total,
                                     page_idx + 1)
            elif page_type in ("detail_left", "detail_right"):
                # Linke oder rechte Hälfte der Draufsicht
                all_x = []
                for c in contours:
                    all_x.extend(c[:, 0].tolist())
                for x, y, d in holes:
                    all_x.append(x)

                if all_x:
                    xmin, xmax = min(all_x), max(all_x)
                    xmid = (xmin + xmax) / 2

                    if page_type == "detail_left":
                        x_range = (xmin, xmid)
                        label = "Detail Links"
                    else:
                        x_range = (xmid, xmax)
                        label = "Detail Rechts"

                    _draw_detail_view_page(fig, contours, holes, params,
                                            config, page_num, page_total,
                                            x_range, label)

            pdf.savefig(fig, bbox_inches="tight", pad_inches=0.2)
            plt.close(fig)

        # Metadaten
        d = pdf.infodict()
        d["Title"] = f"Verifikations-Bericht {params.program_name}"
        d["Author"] = "CAM-Verifikations-Tool"
        d["Subject"] = "Zeichnungsdokumentation"

    return output_path


# --------------------------------------------------------------------------- #
# Bequeme Funktion
# --------------------------------------------------------------------------- #

def create_report(
    contours: List[np.ndarray],
    holes: List[Tuple[float, float, float]],
    output_path: str,
    params: Optional[DrawingParams] = None,
    page_format: str = "A3",
    orientation: str = "landscape",
    include_front: bool = True,
    include_side: bool = True,
    include_iso: bool = True,
    include_hole_list: bool = True,
    auto_detail: bool = False,
    z_scale_factor: float = 1.0,
) -> str:
    """
    Bequeme Schnittstelle für den Multi-Page-Bericht.
    """
    config = MultiPageConfig(
        page_format=page_format,
        orientation=orientation,
        include_cover=True,
        include_top=True,
        include_front=include_front,
        include_side=include_side,
        include_iso=include_iso,
        include_hole_list=include_hole_list,
        auto_detail=auto_detail,
        z_scale_factor=z_scale_factor,
    )
    return create_multipage_drawing(contours, holes, output_path,
                                    params, config)

