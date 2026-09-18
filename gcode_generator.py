"""
gcode_generator.py
------------------
2.5D-Fräs-G-Code aus DXF-Konturen + optionaler Snap und Kollisionsprüfung.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from dxf_loader import DxfContent, Contour
from postprocessors import PostProcessor, ProgramHeader
from snap import plan_approach, snap_point_to_grid
from collision_check import check_program, Warning, summarize


@dataclass
class MachiningParams:
    depth_total: float = -5.0
    step_down: float = -1.0
    feed_xy: int = 400
    feed_z: int = 120
    contour_offset: float = 0.0
    use_tool_comp: bool = True
    approach_distance: float = 5.0   # NEU: Weg vom Anfahrpunkt bis Kontur
    snap_grid: float = 0.0           # NEU: 0 = aus, z.B. 1.0 = 1 mm-Raster


def generate_gcode(
    dxf: DxfContent,
    post: PostProcessor,
    header: ProgramHeader,
    params: MachiningParams,
    contour_layers: List[str] | None = None,
    hole_layers: List[str] | None = None,
    check_collisions: bool = True,
) -> Tuple[str, List[Warning]]:
    """
    Erzeugt den G-Code und prüft ihn optional auf Kollisionen.

    Rückgabe: (gcode_string, warnings)
    """
    lines: List[str] = []

    # ---- Header ----
    lines.extend(post.header(header))
    lines.append("")

    # ---- Konturen ----
    contour_layers = contour_layers or [c.layer for c in dxf.contours]
    relevant_contours = [c for c in dxf.contours if c.layer in contour_layers]

    if relevant_contours:
        lines.append("; --- Konturen ---")
        for idx, contour in enumerate(relevant_contours, 1):
            lines.append(f"; Kontur {idx} (Layer: {contour.layer})")
            lines.extend(_machine_contour(contour, post, header, params))
            lines.append("")

    # ---- Bohrungen ----
    hole_layers = hole_layers or [h.layer for h in dxf.holes]
    relevant_holes = [h for h in dxf.holes if h.layer in hole_layers]

    if relevant_holes:
        lines.append("; --- Bohrungen ---")
        for i, hole in enumerate(relevant_holes, 1):
            lines.append(
                f"; Bohrung {i}: Ø{hole.diameter:.2f} @ "
                f"({hole.x:.2f}, {hole.y:.2f})")
            x, y = hole.x, hole.y
            if params.snap_grid > 0:
                x, y = snap_point_to_grid(x, y, params.snap_grid)
            lines.extend(post.drill(x, y, params.depth_total,
                                    header.safety_height))
        lines.append("")

    lines.extend(post.footer())
    gcode = "\n".join(lines) + "\n"

    # ---- Kollisionsprüfung ----
    warnings: List[Warning] = []
    if check_collisions:
        warnings = check_program(
            gcode,
            contours=relevant_contours,
            safe_z=header.safety_height,
        )
        # Warnungen als Kommentarblock in den G-Code einfügen
        if warnings:
            header_block = ["", "; ===== SICHERHEITSHINWEISE ====="]
            for w in warnings:
                header_block.append(f"; {w.short()}")
            header_block.append("; ===============================")
            header_block.append("")
            gcode = gcode.replace("\n", "\n", 1)  # no-op, sauber
            # einfügen nach Programm-Kopfzeile (nach dem letzten Kopf-Kommentar)
            split_at = gcode.find("\n", gcode.find("\n", gcode.find("\n") + 1) + 1)
            if split_at == -1:
                gcode = gcode + "\n".join(header_block)
            else:
                gcode = gcode[:split_at] + "\n" + "\n".join(header_block) + gcode[split_at:]

    return gcode, warnings


def _machine_contour(
    contour: Contour,
    post: PostProcessor,
    header: ProgramHeader,
    params: MachiningParams,
) -> List[str]:
    """Fährt eine Kontur mit sicherem Anfahrpunkt und optionalem Snap."""
    pts = contour.points.copy()

    # Snap-to-Grid auf alle Konturpunkte (nur wenn aktiv)
    if params.snap_grid > 0:
        xs = np.round(pts[:, 0] / params.snap_grid) * params.snap_grid
        ys = np.round(pts[:, 1] / params.snap_grid) * params.snap_grid
        pts = np.column_stack([xs, ys])

    # Anfahrplan
    plan = plan_approach(
        pts,
        approach_distance=params.approach_distance,
        grid=params.snap_grid,
    )

    lines: List[str] = []
    lines.append(f"; Anfahrpunkt: ({plan.approach[0]:.2f}, {plan.approach[1]:.2f})")
    lines.append(f"; Richtung: {plan.direction.upper()}, "
                 f"Korrektur: {plan.comp_side}")

    # 1) Auf Sicherheitshöhe über den Anfahrpunkt fahren
    lines.append(post.rapid(x=plan.approach[0], y=plan.approach[1],
                            z=header.safety_height))
    # 2) Auf Zwischenhöhe (z.B. 2 mm über Werkstück)
    lines.append(post.rapid(z=2.0))

    # Zustellungen
    from gcode_generator import _z_levels  # lokal halten wir es simpel
    z_levels = _z_levels(params.depth_total, params.step_down)

    tool_comp_on = (
        plan.comp_side
        if (params.use_tool_comp and header.use_radius_comp) else None
    )

    for level_idx, z in enumerate(z_levels, 1):
        lines.append(f"; Zustellung {level_idx}: Z{z:.3f}")

        if tool_comp_on and level_idx == 1:
            lines.append(f"{tool_comp_on} ; Radiuskorrektur ein")

        # Auf Tiefe
        lines.append(post.linear(z=z, f=params.feed_z))
        # Vom Anfahrpunkt zur Kontur (linear, auf Tiefe)
        lines.append(post.linear(x=plan.start[0], y=plan.start[1],
                                 f=params.feed_xy))
        # Kontur abfahren
        for (x, y) in pts[1:]:
            lines.append(post.linear(x=float(x), y=float(y), f=params.feed_xy))
        if contour.closed and not np.allclose(pts[0], pts[-1]):
            lines.append(post.linear(x=plan.start[0], y=plan.start[1],
                                     f=params.feed_xy))

        if tool_comp_on and level_idx == 1:
            lines.append("G40 ; Radiuskorrektur aus")

        if level_idx < len(z_levels):
            lines.append(post.rapid(z=2.0))

    lines.append(post.rapid(z=header.safety_height))
    return lines


def _z_levels(total: float, step: float) -> List[float]:
    total = -abs(total)
    step = -abs(step)
    levels = []
    z = step
    while z > total:
        levels.append(z)
        z += step
    levels.append(total)
    return levels