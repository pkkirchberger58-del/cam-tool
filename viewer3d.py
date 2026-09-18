"""
viewer3d.py
------------
Wiederverwendbares Tkinter-Frame zur Anzeige von STL-Modellen,
DXF-Konturen und G0-Warnsegmenten.
"""

from __future__ import annotations

import os
import threading
import traceback
from dataclasses import dataclass
from typing import Callable, Optional, List

import numpy as np
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg,
    NavigationToolbar2Tk,
)
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection

try:
    from stl import mesh as stl_mesh
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Das Paket 'numpy-stl' fehlt. Bitte installieren mit:\n"
        "    pip install numpy-stl"
    ) from exc


@dataclass
class MeshInfo:
    facet_count: int
    bounds_min: np.ndarray
    bounds_max: np.ndarray

    @property
    def size(self) -> np.ndarray:
        return self.bounds_max - self.bounds_min


class STLViewer(ttk.Frame):
    MAX_FILE_SIZE_MB = 500

    def __init__(
        self,
        master: tk.Misc,
        status_callback: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._status_callback = status_callback or (lambda msg: None)
        self._current_mesh: Optional[stl_mesh.Mesh] = None
        self._mesh_info: Optional[MeshInfo] = None
        self._loading = False
        self._dxf_contours: List[np.ndarray] = []
        self._warning_segments: List[np.ndarray] = []
        self._build_ui()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(side="top", fill="x")

        ttk.Button(toolbar, text="Ansicht zurücksetzen",
                   command=self.reset_view).pack(side="left", padx=2, pady=2)
        self._lbl_stats = ttk.Label(toolbar, text="Kein Modell geladen", anchor="w")
        self._lbl_stats.pack(side="left", padx=8, fill="x", expand=True)

       # self.fig = Figure(figsize=(5, 5), dpi=100, layout="constrained")
        self.fig = Figure(figsize=(5, 5), dpi=100)
        self.ax = self.fig.add_subplot(111, projection="3d")
        self._set_placeholder()

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self._mpl_toolbar = NavigationToolbar2Tk(self.canvas, self, pack_toolbar=False)
        self._mpl_toolbar.update()
        self._mpl_toolbar.pack(side="bottom", fill="x")

    def _set_placeholder(self) -> None:
        self.ax.clear()
        self.ax.set_title("Warte auf Modell …", fontsize=10)
        self.ax.set_xticks([]); self.ax.set_yticks([]); self.ax.set_zticks([])
        self.ax.text2D(0.5, 0.5,
            "Kein Modell geladen.\nOben 'STL laden …' oder 'DXF laden …' klicken.",
            transform=self.ax.transAxes, ha="center", va="center",
            fontsize=10, color="gray")

    # ----------------------------------------------------------- Public API --
    def load_stl(self, file_path: str) -> None:
        if self._loading:
            self._status_callback("Es wird bereits eine Datei geladen …")
            return
        if not file_path or not os.path.isfile(file_path):
            self._status_callback(f"Datei nicht gefunden: {file_path}")
            return
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > self.MAX_FILE_SIZE_MB:
            self._status_callback(f"Datei zu groß ({size_mb:.0f} MB).")
            return

        self._loading = True
        self._status_callback(f"Lade '{os.path.basename(file_path)}' ({size_mb:.1f} MB) …")
        threading.Thread(target=self._load_worker,
                         args=(file_path,), daemon=True).start()

    def set_dxf_contours(self, contours: List[np.ndarray]) -> None:
        """Setzt eine Liste von 2D-Konturen (N,2), die überlagert werden."""
        self._dxf_contours = contours
        self._redraw()

    def set_warning_segments(self, segments: List[np.ndarray]) -> None:
        """
        segments: Liste von (2,3)-Arrays – jeweils Start- und Endpunkt
                  einer als kritisch markierten Bewegung.
        """
        self._warning_segments = segments
        self._redraw()

    def clear(self) -> None:
        self._current_mesh = None
        self._mesh_info = None
        self._dxf_contours = []
        self._warning_segments = []
        self._set_placeholder()
        self._lbl_stats.config(text="Kein Modell geladen")
        self.canvas.draw_idle()

    def reset_view(self) -> None:
        if self._mesh_info is not None:
            self._apply_view(self._mesh_info)
            self.canvas.draw_idle()

    # ----------------------------------------------------------- Internals --
    def _load_worker(self, file_path: str) -> None:
        try:
            loaded_mesh = stl_mesh.Mesh.from_file(file_path)
            if loaded_mesh.vectors.size == 0:
                raise ValueError("STL-Datei enthält keine Dreiecke.")
            info = MeshInfo(
                facet_count=loaded_mesh.vectors.shape[0],
                bounds_min=loaded_mesh.points.reshape(-1, 3).min(axis=0),
                bounds_max=loaded_mesh.points.reshape(-1, 3).max(axis=0),
            )
            self.after(0, self._on_load_success, loaded_mesh, info, file_path)
        except Exception as exc:  # noqa: BLE001
            self.after(0, self._on_load_error, file_path, exc, traceback.format_exc())

    def _on_load_success(self, loaded_mesh, info: MeshInfo, file_path: str) -> None:
        self._loading = False
        self._current_mesh = loaded_mesh
        self._mesh_info = info
        self._redraw()

        size = info.size
        self._lbl_stats.config(
            text=(f"{info.facet_count:,} Facetten | "
                  f"BBox {size[0]:.1f} × {size[1]:.1f} × {size[2]:.1f} mm"
                 ).replace(",", "."))
        self._status_callback(
            f"'{os.path.basename(file_path)}' geladen "
            f"({info.facet_count:,} Facetten)".replace(",", "."))

    def _on_load_error(self, file_path: str, exc: Exception, tb: str) -> None:
        self._loading = False
        print(tb, flush=True)
        self._status_callback(
            f"Fehler beim Laden von '{os.path.basename(file_path)}': "
            f"{type(exc).__name__}: {exc}")

    def _redraw(self) -> None:
        """Zeichnet STL, DXF-Konturen und Warnsegmente neu."""
        self.ax.clear()

        # --- STL ---
        if self._current_mesh is not None:
            coll = Poly3DCollection(
                self._current_mesh.vectors, alpha=0.9,
                edgecolor=(0, 0, 0, 0.15), linewidths=0.2)
            coll.set_facecolor("#3a7bd5")
            self.ax.add_collection3d(coll)
            self.ax.set_xlabel("X (mm)")
            self.ax.set_ylabel("Y (mm)")
            self.ax.set_zlabel("Z (mm)")
            title = "STL + DXF" if self._dxf_contours else "STL"
            self.ax.set_title(title, fontsize=10)
            self._apply_view(self._mesh_info)

        # --- DXF-Konturen auf der Oberfläche des STL ---
        if self._dxf_contours:
            if self._current_mesh is not None:
                z0 = float(self._current_mesh.points.reshape(-1, 3)[:, 2].max())
            else:
                z0 = 0.0

            segs = []
            for c in self._dxf_contours:
                pts3d = np.column_stack(
                    [c[:, 0], c[:, 1], np.full(len(c), z0)])
                segs.append(pts3d)
            lc = Line3DCollection(segs, colors="#ff3030", linewidths=1.4)
            self.ax.add_collection3d(lc)

            if self._current_mesh is None:
                all_pts = np.vstack([np.column_stack(
                    [c[:, 0], c[:, 1], np.zeros(len(c))])
                    for c in self._dxf_contours])
                mn, mx = all_pts.min(0), all_pts.max(0)
                size = np.where(mx - mn < 1e-9, 1.0, mx - mn)
                self.ax.set_xlim(mn[0] - size[0]*0.05, mx[0] + size[0]*0.05)
                self.ax.set_ylim(mn[1] - size[1]*0.05, mx[1] + size[1]*0.05)
                self.ax.set_zlim(-1, 1)
                self.ax.set_box_aspect(
                    (size[0], size[1], max(size[0], size[1])*0.1))
                self.ax.view_init(elev=90, azim=-90)
                self.ax.set_title("DXF-Kontur", fontsize=10)

        # --- Warnsegmente (rot, dicker) ---
        if self._warning_segments:
            lc = Line3DCollection(self._warning_segments,
                                  colors="#ff0000", linewidths=2.5)
            self.ax.add_collection3d(lc)

        # --- Placeholder, falls alles leer ---
        if self._current_mesh is None and not self._dxf_contours:
            self._set_placeholder()

        self.canvas.draw_idle()

    def _apply_view(self, info: MeshInfo) -> None:
        mn, mx = info.bounds_min, info.bounds_max
        size = np.where(mx - mn < 1e-9, 1.0, mx - mn)
        mn = mn - size * 0.02
        mx = mn + size * 1.04
        self.ax.set_xlim(mn[0], mx[0])
        self.ax.set_ylim(mn[1], mx[1])
        self.ax.set_zlim(mn[2], mx[2])
        self.ax.set_box_aspect(size)
        self.ax.view_init(elev=25, azim=-55)