"""
drawing.py
----------
Erzeugt technische Zeichnungen aus DXF-Daten.

Layouts:
- "top"       : nur Draufsicht (bemaßt), A4 quer
- "three"     : Draufsicht + Front + Seite, A3 quer
- "iso"       : Draufsicht + Iso-Perspektive, A3 quer
- "all"       : Draufsicht + Front + Seite + Iso, A3 quer

Bemaßung:
- Bounding-Box (L × B) in der Draufsicht
- Position jeder Bohrung (X, Y)
- Ø jeder Bohrung
- Gesamthöhe in Front-/Seitenansicht
- Bohrtiefe (gestrichelt) in Front-/Seitenansicht
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.backends.backend_pdf import PdfPages


# --------------------------------------------------------------------------- #

@dataclass
class DrawingParams:
    """Zusatzinformationen für den Titelblock und die Seitenansichten."""
    program_name: str = "TEIL"
    program_number: str = "1000"
    tool_name: str = ""
    tool_diameter: float = 0.0
    total_depth: float = 0.0
    stock_height: float = 0.0       # Rohteilhöhe in mm (für Front-/Seitenansicht)
    post_name: str = ""
    units: str = "mm"


# --------------------------------------------------------------------------- #

def _fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _dim_h(ax, x1, x2, y, text, color="#0066cc", lw=1.0):
    ax.annotate("", xy=(x1, y), xytext=(x2, y),
                arrowprops=dict(arrowstyle="<->", color=color, lw=lw))
    ax.text((x1 + x2) / 2, y, text, ha="center", va="bottom",
            color=color, fontsize=8)


def _dim_v(ax, y1, y2, x, text, color="#0066cc", lw=1.0):
    ax.annotate("", xy=(x, y1), xytext=(x, y2),
                arrowprops=dict(arrowstyle="<->", color=color, lw=lw))
    ax.text(x, (y1 + y2) / 2, text, ha="right", va="center",
            color=color, fontsize=8, rotation=90)


# --------------------------------------------------------------------------- #
# Zeichnen der einzelnen Ansichten
# --------------------------------------------------------------------------- #

def _draw_top_view(ax, contours, holes, params: DrawingParams,
                   show_dimensions: bool = True) -> None:
    """Draufsicht (XY) mit Konturen und Bohrungen."""
    all_x, all_y = [], []

    for i, c in enumerate(contours, 1):
        ax.plot(c[:, 0], c[:, 1], "-", color="#1f4e79", linewidth=1.4)
        all_x.extend(c[:, 0].tolist())
        all_y.extend(c[:, 1].tolist())
        cx, cy = c[:, 0].mean(), c[:, 1].mean()
        ax.text(cx, cy, f"K{i}", fontsize=7, color="#1f4e79",
                ha="center", va="center", alpha=0.55)

    for x, y, d in holes:
        circ = Circle((x, y), radius=d / 2, fill=False,
                      edgecolor="#c0392b", linewidth=1.2)
        ax.add_patch(circ)
        cross = d * 0.6
        ax.plot([x - cross, x + cross], [y, y], color="#c0392b",
                lw=0.5, alpha=0.6)
        ax.plot([x, x], [y - cross, y + cross], color="#c0392b",
                lw=0.5, alpha=0.6)
        ax.text(x, y, f"Ø{_fmt(d)}", ha="center", va="center",
                fontsize=7, color="#c0392b", fontweight="bold",
                bbox=dict(facecolor="white", edgecolor="none",
                          alpha=0.75, pad=0.8))
        all_x += [x - d / 2, x + d / 2]
        all_y += [y - d / 2, y + d / 2]

    if show_dimensions and all_x and all_y:
        xmin, xmax = min(all_x), max(all_x)
        ymin, ymax = min(all_y), max(all_y)
        w, h = xmax - xmin, ymax - ymin
        pad = max(w, h) * 0.18 + 3

        # Hauptmaße
        _dim_h(ax, xmin, xmax, ymin - pad * 0.4,
               f"{_fmt(w)} {params.units}")
        _dim_v(ax, ymin, ymax, xmin - pad * 0.4,
               f"{_fmt(h)} {params.units}")

        # Bohrungspositionen
        for x, y, d in holes:
            if abs(x - xmin) > 0.1:
                ax.annotate("", xy=(xmin, y), xytext=(x, y),
                            arrowprops=dict(arrowstyle="<->",
                                            color="#7f8c8d", lw=0.7,
                                            linestyle="--"))
                ax.text((xmin + x) / 2, y + 0.5,
                        _fmt(x - xmin), ha="center", va="bottom",
                        fontsize=6.5, color="#7f8c8d")
            if abs(y - ymin) > 0.1:
                ax.annotate("", xy=(x, ymin), xytext=(x, y),
                            arrowprops=dict(arrowstyle="<->",
                                            color="#7f8c8d", lw=0.7,
                                            linestyle="--"))
                ax.text(x - 0.5, (ymin + y) / 2,
                        _fmt(y - ymin), ha="right", va="center",
                        fontsize=6.5, color="#7f8c8d", rotation=90)

        ax.set_xlim(xmin - pad, xmax + pad)
        ax.set_ylim(ymin - pad, ymax + pad)

    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.5)
    ax.axhline(0, color="#888", lw=0.4)
    ax.axvline(0, color="#888", lw=0.4)
    ax.set_xlabel(f"X ({params.units})", fontsize=8)
    ax.set_ylabel(f"Y ({params.units})", fontsize=8)
    ax.set_title("Draufsicht", fontsize=10, fontweight="bold", pad=6)
    ax.tick_params(labelsize=7)


def _draw_front_view(ax, contours, holes, params: DrawingParams) -> None:
    """
    Frontansicht (XZ): 
    zeigt die Werkstücklänge, Höhe und Bohrtiefen als gestrichelte Linien.
    """
    # Umriss aus Bounding-Box der Draufsicht
    all_x = []
    for c in contours:
        all_x.extend(c[:, 0].tolist())
    for x, y, d in holes:
        all_x += [x - d / 2, x + d / 2]

    if not all_x:
        ax.text(0.5, 0.5, "keine Geometrie", ha="center", va="center")
        return

    xmin, xmax = min(all_x), max(all_x)
    height = params.stock_height if params.stock_height > 0 else abs(params.total_depth) * 2
    if height <= 0:
        height = 10.0

    # Rohteil-Umriss
    ax.add_patch(plt.Rectangle((xmin, 0), xmax - xmin, height,
                               fill=False, edgecolor="#1f4e79",
                               linewidth=1.4))

    # Bohrungen als gestrichelte Linien nach unten
    for x, y, d in holes:
        ax.plot([x - d / 2, x - d / 2], [height, height - abs(params.total_depth)],
                color="#c0392b", lw=0.9, linestyle="--")
        ax.plot([x + d / 2, x + d / 2], [height, height - abs(params.total_depth)],
                color="#c0392b", lw=0.9, linestyle="--")

    # Bemaßung
    pad = max(xmax - xmin, height) * 0.15 + 2
    _dim_h(ax, xmin, xmax, -pad * 0.5, f"{_fmt(xmax - xmin)} {params.units}")
    _dim_v(ax, 0, height, xmin - pad * 0.5, f"{_fmt(height)} {params.units}")

    ax.set_xlim(xmin - pad, xmax + pad)
    ax.set_ylim(-pad, height + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.5)
    ax.set_xlabel(f"X ({params.units})", fontsize=8)
    ax.set_ylabel(f"Z ({params.units})", fontsize=8)
    ax.set_title("Frontansicht", fontsize=10, fontweight="bold", pad=6)
    ax.tick_params(labelsize=7)


def _draw_side_view(ax, contours, holes, params: DrawingParams) -> None:
    """Seitenansicht (YZ): analog zur Frontansicht, nur in Y."""
    all_y = []
    for c in contours:
        all_y.extend(c[:, 1].tolist())
    for x, y, d in holes:
        all_y += [y - d / 2, y + d / 2]

    if not all_y:
        ax.text(0.5, 0.5, "keine Geometrie", ha="center", va="center")
        return

    ymin, ymax = min(all_y), max(all_y)
    height = params.stock_height if params.stock_height > 0 else abs(params.total_depth) * 2
    if height <= 0:
        height = 10.0

    ax.add_patch(plt.Rectangle((ymin, 0), ymax - ymin, height,
                               fill=False, edgecolor="#1f4e79",
                               linewidth=1.4))

    for x, y, d in holes:
        ax.plot([y - d / 2, y - d / 2], [height, height - abs(params.total_depth)],
                color="#c0392b", lw=0.9, linestyle="--")
        ax.plot([y + d / 2, y + d / 2], [height, height - abs(params.total_depth)],
                color="#c0392b", lw=0.9, linestyle="--")

    pad = max(ymax - ymin, height) * 0.15 + 2
    _dim_h(ax, ymin, ymax, -pad * 0.5, f"{_fmt(ymax - ymin)} {params.units}")
    _dim_v(ax, 0, height, ymin - pad * 0.5, f"{_fmt(height)} {params.units}")

    ax.set_xlim(ymin - pad, ymax + pad)
    ax.set_ylim(-pad, height + pad)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, linestyle=":", linewidth=0.4, alpha=0.5)
    ax.set_xlabel(f"Y ({params.units})", fontsize=8)
    ax.set_ylabel(f"Z ({params.units})", fontsize=8)
    ax.set_title("Seitenansicht", fontsize=10, fontweight="bold", pad=6)
    ax.tick_params(labelsize=7)


def _draw_iso_view(ax, contours, holes, params: DrawingParams) -> None:
    """Isometrische 3D-Ansicht mit matplotlib 3D-Achse."""
    height = params.stock_height if params.stock_height > 0 else abs(params.total_depth) * 2
    if height <= 0:
        height = 10.0

    # Bounding-Box bestimmen
    all_x, all_y = [], []
    for c in contours:
        all_x.extend(c[:, 0].tolist())
        all_y.extend(c[:, 1].tolist())
    for x, y, d in holes:
        all_x += [x - d / 2, x + d / 2]
        all_y += [y - d / 2, y + d / 2]

    if not all_x or not all_y:
        ax.text2D(0.5, 0.5, "keine Geometrie",
                  transform=ax.transAxes, ha="center", va="center")
        return

    xmin, xmax = min(all_x), max(all_x)
    ymin, ymax = min(all_y), max(all_y)

    # ---- Rohteil-Box (Kanten) ----
    corners = [
        (xmin, ymin, 0), (xmax, ymin, 0), (xmax, ymax, 0), (xmin, ymax, 0),
        (xmin, ymin, height), (xmax, ymin, height),
        (xmax, ymax, height), (xmin, ymax, height),
    ]
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),       # unten
        (4, 5), (5, 6), (6, 7), (7, 4),       # oben
        (0, 4), (1, 5), (2, 6), (3, 7),       # vertikal
    ]
    for i, j in edges:
        ax.plot([corners[i][0], corners[j][0]],
                [corners[i][1], corners[j][1]],
                [corners[i][2], corners[j][2]],
                color="#1f4e79", lw=1.0)

    # ---- Konturen auf der Oberfläche ----
    for c in contours:
        ax.plot(c[:, 0], c[:, 1], np.full(len(c), height),
                color="#3a7bd5", lw=1.2)

    # ---- Bohrungen ----
    z_bot = max(0.0, height - abs(params.total_depth))
    for x, y, d in holes:
        # Vertikale Linie mit 2 Punkten (statt 30)
        ax.plot([x, x], [y, y], [height, z_bot],
                color="#c0392b", lw=1.2, linestyle="--")
        # Kreis auf der Oberfläche
        t = np.linspace(0, 2 * np.pi, 40)
        cx = x + (d / 2) * np.cos(t)
        cy = y + (d / 2) * np.sin(t)
        cz = np.full_like(cx, height)
        ax.plot(cx, cy, cz, color="#c0392b", lw=1.0)

    # ---- Limits und Seitenverhältnis ----
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_zlim(0, height)
    ax.set_box_aspect((xmax - xmin, ymax - ymin, height))

    ax.view_init(elev=25, azim=-55)
    ax.set_xlabel(f"X ({params.units})", fontsize=7)
    ax.set_ylabel(f"Y ({params.units})", fontsize=7)
    ax.set_zlabel(f"Z ({params.units})", fontsize=7)
    ax.set_title("Isometrie", fontsize=10, fontweight="bold", pad=6)
    ax.tick_params(labelsize=6)

# --------------------------------------------------------------------------- #
# Titelblock
# --------------------------------------------------------------------------- #

def _draw_title_block(ax, params: DrawingParams,
                      n_contours: int, n_holes: int) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(plt.Rectangle((0.01, 0.05), 0.98, 0.9,
                               fill=False, edgecolor="#1f4e79",
                               linewidth=1.2, transform=ax.transAxes))

    left_lines = [
        ("Programm",  f"{params.program_number} – {params.program_name}"),
        ("Werkzeug",  f"{params.tool_name}   Ø{_fmt(params.tool_diameter)} {params.units}"),
        ("Tiefe",     f"{_fmt(abs(params.total_depth))} {params.units}"),
        ("Steuerung", params.post_name),
    ]
    y = 0.78
    for label, value in left_lines:
        ax.text(0.03, y, f"{label}:", fontsize=8,
                color="#555", transform=ax.transAxes)
        ax.text(0.15, y, value, fontsize=8,
                color="#000", fontweight="bold", transform=ax.transAxes)
        y -= 0.20

    right_lines = [
        ("Konturen",  f"{n_contours}"),
        ("Bohrungen", f"{n_holes}"),
        ("Datum",     datetime.datetime.now().strftime("%d.%m.%Y  %H:%M")),
    ]
    y = 0.78
    for label, value in right_lines:
        ax.text(0.55, y, f"{label}:", fontsize=8,
                color="#555", transform=ax.transAxes)
        ax.text(0.68, y, value, fontsize=8,
                color="#000", fontweight="bold", transform=ax.transAxes)
        y -= 0.20

    # Legende
    ax.plot([0.85, 0.88], [0.78, 0.78], color="#1f4e79",
            lw=1.4, transform=ax.transAxes)
    ax.text(0.895, 0.78, "Konturen", fontsize=7,
            va="center", transform=ax.transAxes)

    ax.plot([0.85, 0.88], [0.55, 0.55], color="#c0392b",
            lw=1.4, transform=ax.transAxes)
    ax.text(0.895, 0.55, "Bohrungen", fontsize=7,
            va="center", transform=ax.transAxes)


# --------------------------------------------------------------------------- #
# Hauptfunktion
# --------------------------------------------------------------------------- #

def create_drawing(
    contours: List[np.ndarray],
    holes: List[Tuple[float, float, float]],
    output_path: str,
    params: Optional[DrawingParams] = None,
    mode: str = "three",
    dpi: int = 200,
) -> str:
    """
    Erzeugt eine technische Zeichnung und speichert sie als PDF oder PNG.

    mode:
        "top"    – nur Draufsicht, A4 quer
        "three"  – Draufsicht + Front + Seite, A3 quer  (Standard)
        "iso"    – Draufsicht + Iso, A3 quer
        "all"    – Draufsicht + Front + Seite + Iso, A3 quer
    """
    params = params or DrawingParams()

    # Layout wählen
    if mode == "top":
        fig = plt.figure(figsize=(11.7, 8.3), dpi=dpi)
        gs = fig.add_gridspec(2, 1, height_ratios=[5, 1], hspace=0.15)
        ax_top = fig.add_subplot(gs[0])
        _draw_top_view(ax_top, contours, holes, params, show_dimensions=True)
        ax_tb = fig.add_subplot(gs[1])
        _draw_title_block(ax_tb, params, len(contours), len(holes))

    elif mode == "three":
        fig = plt.figure(figsize=(16.5, 11.7), dpi=dpi)   # A3 quer
        gs = fig.add_gridspec(3, 2, height_ratios=[3, 3, 1],
                              width_ratios=[1, 1], hspace=0.35, wspace=0.25)
        ax_top = fig.add_subplot(gs[0, 0])
        _draw_top_view(ax_top, contours, holes, params, show_dimensions=True)

        ax_front = fig.add_subplot(gs[0, 1])
        _draw_front_view(ax_front, contours, holes, params)

        ax_side = fig.add_subplot(gs[1, 0])
        _draw_side_view(ax_side, contours, holes, params)

        # Platzhalter für später (z.B. Detail)
        ax_empty = fig.add_subplot(gs[1, 1])
        ax_empty.axis("off")
        ax_empty.text(0.5, 0.5, "Reserve",
                      ha="center", va="center", color="#bbb", fontsize=10)

        ax_tb = fig.add_subplot(gs[2, :])
        _draw_title_block(ax_tb, params, len(contours), len(holes))

    elif mode == "iso":
        fig = plt.figure(figsize=(16.5, 11.7), dpi=dpi)
        gs = fig.add_gridspec(3, 2, height_ratios=[4, 4, 1],
                              width_ratios=[3, 4], hspace=0.3, wspace=0.2)
        ax_top = fig.add_subplot(gs[0, 0])
        _draw_top_view(ax_top, contours, holes, params, show_dimensions=True)

        ax_iso = fig.add_subplot(gs[:, 1], projection="3d")
        _draw_iso_view(ax_iso, contours, holes, params)

        ax_front = fig.add_subplot(gs[1, 0])
        _draw_front_view(ax_front, contours, holes, params)

        ax_tb = fig.add_subplot(gs[2, :])
        _draw_title_block(ax_tb, params, len(contours), len(holes))

    elif mode == "all":
        fig = plt.figure(figsize=(16.5, 11.7), dpi=dpi)   # A3 quer
        gs = fig.add_gridspec(3, 3, height_ratios=[4, 4, 1],
                              width_ratios=[3, 3, 4], hspace=0.35, wspace=0.25)

        ax_top = fig.add_subplot(gs[0, 0])
        _draw_top_view(ax_top, contours, holes, params, show_dimensions=True)

        ax_front = fig.add_subplot(gs[0, 1])
        _draw_front_view(ax_front, contours, holes, params)

        ax_side = fig.add_subplot(gs[1, 0])
        _draw_side_view(ax_side, contours, holes, params)

        ax_iso = fig.add_subplot(gs[:, 2], projection="3d")
        _draw_iso_view(ax_iso, contours, holes, params)

        ax_tb = fig.add_subplot(gs[2, :])
        _draw_title_block(ax_tb, params, len(contours), len(holes))

    else:
        raise ValueError(f"Unbekannter Modus: {mode}")

    # Export
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".pdf":
        with PdfPages(output_path) as pdf:
            pdf.savefig(fig, bbox_inches="tight")
            d = pdf.infodict()
            d["Title"] = f"Zeichnung {params.program_name}"
            d["Author"] = "CAM-Tool"
        saved = output_path
    elif ext in (".png", ".jpg", ".jpeg"):
        fig.savefig(output_path, bbox_inches="tight", dpi=dpi)
        saved = output_path
    else:
        if not ext:
            output_path += ".pdf"
        with PdfPages(output_path) as pdf:
            pdf.savefig(fig, bbox_inches="tight")
        saved = output_path

    plt.close(fig)
    return saved