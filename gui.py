"""
gui.py
------
Hauptfenster der CAM-Anwendung.

Layout:
    ┌─────────────────────────────────────────────────────────┐
    │ Werkzeugleiste: STL laden | DXF laden | Leeren          │
    ├───────────────┬──────────────────┬──────────────────────┤
    │ Parameter     │ G-Code-Vorschau  │ 3D-Modell            │
    │ (Werkzeug,    │ (editierbar)     │ (STL + DXF-Overlay)  │
    │  Vorschub…)   │                  │                      │
    ├───────────────┴──────────────────┴──────────────────────┤
    │ Statuszeile                                              │
    └─────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from viewer3d import STLViewer
from dxf_loader import load_dxf
from gcode_generator import MachiningParams, generate_gcode
from postprocessors import ProgramHeader, POSTPROCESSORS, create_postprocessor
from collision_check import summarize

from config import AppConfig
from tools_db import ToolDatabase
from tools_editor import ToolEditorDialog
from drawing import create_drawing, DrawingParams


class CamApp(tk.Tk):
    APP_TITLE = "Sinumerik / Heidenhain CAM-Tool"
    MIN_SIZE = (1100, 680)

    # ==================================================================
    # Initialisierung
    # ==================================================================
    def __init__(self) -> None:
        super().__init__()
        self.title(self.APP_TITLE)
        self.minsize(*self.MIN_SIZE)

        # ---- 1) Config & Werkzeug-DB ZUERST laden ----
        self.config = AppConfig.load()
        self.tools_db = ToolDatabase(self.config.tools_db_path)

        # ---- 2) Fenstergeometrie aus Config ----
        if self.config.window_geometry:
            try:
                self.geometry(self.config.window_geometry)
            except tk.TclError:
                self.geometry("1350x780")
        else:
            self.geometry("1350x780")

        # ---- 3) Theme ----
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")

        # ---- 4) Laufzeitzustand ----
        self._dxf_content = None
        self._stl_path: str | None = None
        self._dxf_path: str | None = None
        self._last_warnings: list = []

        # ---- 5) UI bauen (Statusbar VOR Main-Area) ----
        self._build_top_panel()
        self._build_statusbar()
        self._build_main_area()

        # ---- 6) Fensterschließen abfangen ----
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================================================================
    # Config-Speicherung beim Schließen
    # ==================================================================
    def _on_close(self) -> None:
        """Speichert Config und beendet die App."""
        try:
            self._save_config()
        except Exception as exc:  # noqa: BLE001
            print(f"[gui] Config konnte nicht gespeichert werden: {exc}")
        self.destroy()

    def _save_config(self) -> None:
        """Schreibt alle relevanten Einstellungen in config.json."""
        cfg = self.config

        # Fenster
        cfg.window_geometry = self.geometry()

        # Letzte Parameter
        cfg.last_tool_id          = self.var_tool_id.get()
        cfg.last_program_number   = self.var_prog_number.get()
        cfg.last_program_name     = self.var_prog_name.get()
        cfg.last_speed            = self.var_speed.get()
        cfg.last_feed_xy          = self.var_feed_xy.get()
        cfg.last_feed_z           = self.var_feed_z.get()
        cfg.last_depth            = self.var_depth.get()
        cfg.last_step             = self.var_step.get()
        cfg.last_safety           = self.var_safety.get()
        cfg.last_offset           = self.var_offset.get()
        cfg.last_snap_grid        = self.var_snap_grid.get()
        cfg.last_approach_dist    = self.var_approach_dist.get()
        cfg.last_coolant          = self.var_coolant.get()
        cfg.last_use_comp         = self.var_use_comp.get()
        cfg.last_comp_side        = self.var_comp_side.get()
        cfg.last_post             = self.var_post.get()
        cfg.last_check_collisions = self.var_check_collisions.get()

        # Letzte Verzeichnisse
        if self._stl_path:
            cfg.last_stl_dir = os.path.dirname(self._stl_path)
        if self._dxf_path:
            cfg.last_dxf_dir = os.path.dirname(self._dxf_path)

        cfg.save()

    # ==================================================================
    # Aufbau: Werkzeugleiste
    # ==================================================================
    def _build_top_panel(self) -> None:
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(side="top", fill="x")

        ttk.Button(top, text="STL laden …", command=self._on_browse_stl)\
            .pack(side="left", padx=2)
        ttk.Button(top, text="DXF laden …", command=self._on_browse_dxf)\
            .pack(side="left", padx=2)
        ttk.Button(top, text="Alles leeren", command=self._on_clear_all)\
            .pack(side="left", padx=2)

        self.lbl_files = ttk.Label(top, text="Keine Dateien geladen",
                                   anchor="w", foreground="#a00")
        self.lbl_files.pack(side="left", fill="x", expand=True, padx=(12, 0))

    # ==================================================================
    # Aufbau: Statusbar
    # ==================================================================
    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, relief="sunken")
        bar.pack(side="bottom", fill="x")
        self._status_var = tk.StringVar(value="Bereit.")
        ttk.Label(bar, textvariable=self._status_var,
                  anchor="w", padding=(6, 2))\
            .pack(side="left", fill="x", expand=True)

    # ==================================================================
    # Aufbau: Hauptbereich (3 Spalten)
    # ==================================================================
    def _build_main_area(self) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self._paned = paned

        # ------------------------------------------------------------------
        # LINKE SPALTE – CNC-Parameter
        # ------------------------------------------------------------------
        left = ttk.LabelFrame(paned, text="CNC-Parameter", padding=10)
        left.columnconfigure(1, weight=1)

        # ---- Steuerung / Postprozessor (Zeile 0) ----
        ttk.Label(left, text="Steuerung:").grid(row=0, column=0, sticky="w", pady=2)
        self.var_post = tk.StringVar(
            value=self.config.last_post or list(POSTPROCESSORS.keys())[0])
        ttk.Combobox(left, textvariable=self.var_post,
                     values=list(POSTPROCESSORS.keys()),
                     state="readonly", width=28)\
            .grid(row=0, column=1, sticky="ew", pady=2)

        # ---- Werkzeug-Auswahl (Zeile 1) ----
        ttk.Label(left, text="Werkzeug:").grid(row=1, column=0, sticky="w", pady=2)
        self.var_tool_id = tk.StringVar(value=self.config.last_tool_id or "")

        tool_labels = self._build_tool_labels()
        self.cmb_tool = ttk.Combobox(
            left, textvariable=self.var_tool_id,
            values=tool_labels, state="readonly", width=28)
        self.cmb_tool.grid(row=1, column=1, sticky="ew", pady=2)
        self.cmb_tool.bind("<<ComboboxSelected>>", self._on_tool_selected)

        # ---- Werkzeug-DB-Button (Zeile 2) ----
        ttk.Button(left, text="Werkzeug-DB bearbeiten …",
                   command=self._on_edit_tools)\
            .grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 8))

        # ---- Parameter-Variablen (aus Config vorbelegt) ----
        self.var_prog_number = tk.StringVar(value=self.config.last_program_number)
        self.var_prog_name   = tk.StringVar(value=self.config.last_program_name)
        self.var_tool        = tk.StringVar(value="1")
        self.var_speed       = tk.StringVar(value=self.config.last_speed)
        self.var_feed_xy     = tk.StringVar(value=self.config.last_feed_xy)
        self.var_feed_z      = tk.StringVar(value=self.config.last_feed_z)
        self.var_depth       = tk.StringVar(value=self.config.last_depth)
        self.var_step        = tk.StringVar(value=self.config.last_step)
        self.var_safety      = tk.StringVar(value=self.config.last_safety)
        self.var_offset      = tk.StringVar(value=self.config.last_offset)
        self.var_coolant     = tk.BooleanVar(value=self.config.last_coolant)
        self.var_use_comp    = tk.BooleanVar(value=self.config.last_use_comp)
        self.var_comp_side   = tk.StringVar(value=self.config.last_comp_side)

        # Snap / Anfahrweg / Kollisionsprüfung
        self.var_snap_grid = tk.StringVar(value=self.config.last_snap_grid)
        self.var_approach_dist = tk.StringVar(value=self.config.last_approach_dist)
        self.var_check_collisions = tk.BooleanVar(
            value=self.config.last_check_collisions)

        # Rohteilhöhe für Front-/Seitenansicht der Zeichnung
        self.var_stock_height = tk.StringVar(
            value=self.config.last_stock_height)

        # Zeichnungsmodus (top / three / iso / all)
        self.var_drawing_mode = tk.StringVar(
            value=self.config.last_drawing_mode)

        # ---- Hilfsfunktion für Eingabezeilen ----
        def add_row(r: int, label: str, var: tk.Variable, width: int = 10) -> None:
            ttk.Label(left, text=label).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(left, textvariable=var, width=width)\
                .grid(row=r, column=1, sticky="ew", pady=2)

        # ---- Parameter-Zeilen (Zeilen 3–15) ----
        add_row(3,  "Programmnummer:",   self.var_prog_number)
        add_row(4,  "Programmname:",     self.var_prog_name)
        add_row(5,  "Werkzeug T:",       self.var_tool)
        add_row(6,  "Drehzahl S:",       self.var_speed)
        add_row(7,  "Vorschub F (XY):",  self.var_feed_xy)
        add_row(8,  "Vorschub F (Z):",   self.var_feed_z)
        add_row(9,  "Gesamttiefe Z:",    self.var_depth)
        add_row(10, "Zustellung ap:",    self.var_step)
        add_row(11, "Sicherheitshöhe:",  self.var_safety)
        add_row(12, "Nullpunkt:",        self.var_offset)
        add_row(13, "Snap-Raster (mm):", self.var_snap_grid)
        add_row(14, "Anfahrweg (mm):",   self.var_approach_dist)
        add_row(15, "Rohteilhöhe Z:",    self.var_stock_height)

        # ---- Checkboxen (Zeilen 16–18) ----
        ttk.Checkbutton(left, text="Kollisionsprüfung aktiv",
                        variable=self.var_check_collisions)\
            .grid(row=16, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(left, text="Kühlmittel M8",
                        variable=self.var_coolant)\
            .grid(row=17, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(left, text="Radiuskorrektur G41/G42",
                        variable=self.var_use_comp)\
            .grid(row=18, column=0, columnspan=2, sticky="w")

        # ---- Korrekturseite (Zeile 19) ----
        ttk.Label(left, text="Korrekturseite:")\
            .grid(row=19, column=0, sticky="w", pady=2)
        ttk.Combobox(left, textvariable=self.var_comp_side,
                     values=["left", "right"], state="readonly", width=8)\
            .grid(row=19, column=1, sticky="w")

        # ---- Zeichnungsmodus (Zeile 20) ----
        ttk.Label(left, text="Zeichnung:")\
            .grid(row=20, column=0, sticky="w", pady=2)
        ttk.Combobox(left, textvariable=self.var_drawing_mode,
                     values=["top", "three", "iso", "all"],
                     state="readonly", width=10)\
            .grid(row=20, column=1, sticky="w")

        # ---- Trennlinie (Zeile 21) ----
        ttk.Separator(left, orient="horizontal")\
            .grid(row=21, column=0, columnspan=2, sticky="ew", pady=10)

        # ---- Buttons (Zeilen 22–24) ----
        ttk.Button(left, text="G-Code generieren",
                   command=self._on_generate_gcode)\
            .grid(row=22, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(left, text="G-Code speichern …",
                   command=self._on_save_gcode)\
            .grid(row=23, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Button(left, text="Bemaßte Zeichnung …",
                   command=self._on_export_drawing)\
            .grid(row=24, column=0, columnspan=2, sticky="ew", pady=(8, 2))

        paned.add(left, weight=0)

        # ---- Werkzeug-Vorauswahl aus Config anwenden ----
        if self.var_tool_id.get():
            self._apply_tool_by_label(self.var_tool_id.get())

        # ------------------------------------------------------------------
        # MITTLERE SPALTE – G-Code-Vorschau
        # ------------------------------------------------------------------
        mid = ttk.LabelFrame(paned, text="G-Code Vorschau (editierbar)", padding=4)
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)

        self.txt_preview = tk.Text(
            mid, wrap="none", font=("Consolas", 10),
            bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="#d4d4d4", undo=True)
        self.txt_preview.grid(row=0, column=0, sticky="nsew")

        yscroll = ttk.Scrollbar(mid, orient="vertical",
                                command=self.txt_preview.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(mid, orient="horizontal",
                                command=self.txt_preview.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        self.txt_preview.configure(yscrollcommand=yscroll.set,
                                   xscrollcommand=xscroll.set)
        paned.add(mid, weight=1)

        # ------------------------------------------------------------------
        # RECHTE SPALTE – 3D-Ansicht
        # ------------------------------------------------------------------
        right = ttk.LabelFrame(paned, text="3D-Ansicht (STL + DXF)", padding=4)
        self.viewer = STLViewer(right, status_callback=self.set_status)
        self.viewer.pack(fill="both", expand=True)
        paned.add(right, weight=1)



    def _on_export_drawing(self) -> None:
        """Erzeugt eine bemaßte Zeichnung als PDF oder PNG."""
        if self._dxf_content is None:
            messagebox.showinfo("Keine Daten",
                                "Bitte zuerst eine DXF-Datei laden.")
            return

        # Dateiname vorschlagen
        default_name = self.var_prog_name.get().strip() or "Zeichnung"
        path = filedialog.asksaveasfilename(
            title="Bemaßte Zeichnung speichern",
            initialdir=self.config.last_save_dir or None,
            initialfile=f"{default_name}_Zeichnung.pdf",
            defaultextension=".pdf",
            filetypes=[("PDF-Datei", "*.pdf"),
                       ("PNG-Bild", "*.png"),
                       ("Alle Dateien", "*.*")])
        if not path:
            return

        # Postprozessor und Werkzeug für Titelblock
        post = create_postprocessor(self.var_post.get())
        tool = self.tools_db.get(
            self.var_tool_id.get().split(" – ")[0].strip())

        # Parameter sicher einlesen
        try:
            depth = float(self.var_depth.get().replace(",", "."))
        except (ValueError, AttributeError):
            depth = 0.0

        try:
            stock = float(self.var_stock_height.get().replace(",", "."))
            if stock <= 0:
                stock = 20.0
        except (ValueError, AttributeError):
            stock = 20.0

        params = DrawingParams(
            program_name=self.var_prog_name.get().strip() or "TEIL",
            program_number=self.var_prog_number.get().strip() or "1000",
            tool_name=tool.name if tool else f"T{self.var_tool.get()}",
            tool_diameter=tool.diameter if tool else 0.0,
            total_depth=depth,
            stock_height=stock,
            post_name=post.label,
            units=self._dxf_content.units or "mm",
        )

        # Konturen und Bohrungen
        contours = [c.points for c in self._dxf_content.contours]
        holes = [(h.x, h.y, h.diameter) for h in self._dxf_content.holes]

        # ⭐ HIER: Modus aus dem Dropdown lesen
        mode = self.var_drawing_mode.get()
        print(f"[DEBUG] Exportiere Zeichnung mit mode='{mode}'")   # temporär

        try:
            saved = create_drawing(contours, holes, path, params,
                                   mode=mode)
        except Exception as exc:
            messagebox.showerror("Zeichnung fehlgeschlagen",
                                 f"Konnte Zeichnung nicht erzeugen:\n{exc}")
            return

        self.config.last_save_dir = os.path.dirname(saved)
        self.set_status(f"Zeichnung ({mode}) gespeichert: "
                        f"{os.path.basename(saved)}")

        if messagebox.askyesno(
            "Zeichnung erstellt",
            f"Gespeichert: {os.path.basename(saved)}\n\nJetzt öffnen?"):
            try:
                os.startfile(saved)
            except AttributeError:
                import subprocess, sys
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, saved])





    # ==================================================================
    # Werkzeugverwaltung
    # ==================================================================
    def _build_tool_labels(self) -> list[str]:
        """Erzeugt Anzeige-Labels für das Dropdown aus der Werkzeug-DB."""
        return [f"{t.id} – {t.name} (Ø{t.diameter:g})"
                for t in self.tools_db.tools]

    def _on_tool_selected(self, _event=None) -> None:
        """Wird ausgelöst, wenn der Benutzer im Dropdown ein Werkzeug wählt."""
        self._apply_tool_by_label(self.var_tool_id.get())

    def _apply_tool_by_label(self, label: str) -> None:
        """Setzt die Parameter-Felder passend zum gewählten Werkzeug."""
        if not label:
            return
        tool_id = label.split(" – ", 1)[0].strip()
        tool = self.tools_db.get(tool_id)
        if tool is None:
            return

        # Werkzeugnummer (T-Wert) aus ID extrahieren: "T01" → 1
        digits = "".join(ch for ch in tool.id if ch.isdigit())
        self.var_tool.set(str(int(digits)) if digits else "1")

        # Drehzahl: Mittelwert
        self.var_speed.set(str(tool.rpm_default()))

        # Vorschub XY: Mittelwert; Z konservativ 1/3 davon
        if tool.feed_default() > 0:
            self.var_feed_xy.set(str(tool.feed_default()))
            self.var_feed_z.set(str(max(30, tool.feed_default() // 3)))

        self.set_status(
            f"Werkzeug '{tool.id}' geladen: Ø{tool.diameter:g} mm, "
            f"Z{tool.flutes}, {tool.material} {tool.coating}")

    def _on_edit_tools(self) -> None:
        """Öffnet den Werkzeug-Bearbeitungsdialog."""
        dlg = ToolEditorDialog(self, self.tools_db)
        self.wait_window(dlg)

        tool_labels = self._build_tool_labels()
        self.cmb_tool.configure(values=tool_labels)

        current = self.var_tool_id.get()
        if current and current not in tool_labels:
            self.var_tool_id.set(tool_labels[0] if tool_labels else "")
            if tool_labels:
                self._apply_tool_by_label(tool_labels[0])

    # ==================================================================
    # Datei-Aktionen
    # ==================================================================
    def _on_browse_stl(self) -> None:
        path = filedialog.askopenfilename(
            title="STL-Datei auswählen",
            initialdir=self.config.last_stl_dir or None,
            filetypes=[("3D-Modelle (STL)", "*.stl"),
                       ("Alle Dateien", "*.*")])
        if not path:
            return
        self._stl_path = path
        self._update_file_label()
        self.viewer.load_stl(path)

    def _on_browse_dxf(self) -> None:
        path = filedialog.askopenfilename(
            title="DXF-Datei auswählen",
            initialdir=self.config.last_dxf_dir or None,
            filetypes=[("DXF-Zeichnungen", "*.dxf"),
                       ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            content = load_dxf(path)
        except Exception as exc:
            messagebox.showerror("DXF-Fehler",
                                 f"Konnte DXF nicht lesen:\n{exc}")
            return

        self._dxf_content = content
        self._dxf_path = path
        self._update_file_label()

        contours = [c.points for c in content.contours]
        self.viewer.set_dxf_contours(contours)

        n_c = len(content.contours)
        n_h = len(content.holes)
        self.set_status(
            f"DXF geladen: {n_c} Konturen, {n_h} Bohrungen, "
            f"Layer: {', '.join(content.layers) or '—'}")

    def _on_clear_all(self) -> None:
        self._dxf_content = None
        self._stl_path = None
        self._dxf_path = None
        self.viewer.clear()
        self.txt_preview.delete("1.0", "end")
        self._update_file_label()
        self.set_status("Alles geleert.")

    def _update_file_label(self) -> None:
        parts = []
        if self._stl_path:
            parts.append(f"STL: {os.path.basename(self._stl_path)}")
        if self._dxf_path:
            parts.append(f"DXF: {os.path.basename(self._dxf_path)}")

        if not self._dxf_path:
            # Keine DXF – großer Warnhinweis
            text = " | ".join(parts) + "  ⚠ Ohne DXF kein echtes Fräsprogramm möglich"
            self.lbl_files.config(text=text, foreground="#c00")
        elif parts:
            self.lbl_files.config(text=" | ".join(parts), foreground="#060")
        else:
            self.lbl_files.config(text="Keine Dateien geladen", foreground="#a00")

    # ==================================================================
    # G-Code-Erzeugung
    # ==================================================================
    def _collect_header(self) -> ProgramHeader | None:
        try:
            return ProgramHeader(
                program_number=self.var_prog_number.get().strip() or "1000",
                program_name=self.var_prog_name.get().strip() or "TEIL",
                tool_number=int(self.var_tool.get()),
                spindle_speed=int(self.var_speed.get()),
                feed_rate=int(self.var_feed_xy.get()),
                coolant=self.var_coolant.get(),
                safety_height=float(self.var_safety.get().replace(",", ".")),
                work_offset=self.var_offset.get().strip() or "G54",
                use_radius_comp=self.var_use_comp.get(),
                radius_comp_side=self.var_comp_side.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Ungültige Eingabe",
                                 f"Bitte Zahlen prüfen:\n{exc}")
            return None

    def _collect_params(self) -> MachiningParams | None:
        try:
            return MachiningParams(
                depth_total=float(self.var_depth.get().replace(",", ".")),
                step_down=float(self.var_step.get().replace(",", ".")),
                feed_xy=int(self.var_feed_xy.get()),
                feed_z=int(self.var_feed_z.get()),
                approach_distance=float(
                    self.var_approach_dist.get().replace(",", ".")),
                snap_grid=float(
                    self.var_snap_grid.get().replace(",", ".")),
            )
        except ValueError as exc:
            messagebox.showerror("Ungültige Eingabe",
                                 f"Bitte Zahlen prüfen:\n{exc}")
            return None

    def _on_generate_gcode(self) -> None:
        # ---- Neue Sicherheitsabfrage ----
        if self._dxf_content is None:
            msg = (
                "Es ist keine DXF geladen.\n\n"
                "Eine STL enthält nur die 3D-Oberfläche und KEINE\n"
                "2D-Fräskonturen oder Bohrungen. Ohne DXF kann kein\n"
                "echter G-Code für dein Bauteil erzeugt werden.\n\n"
                "Möchtest du den Demo-G-Code (Quadrat 100×100 +\n"
                "eine Bohrung) zum Testen erzeugen?"
            )
            if not messagebox.askyesno("Kein echtes Programm möglich", msg):
                self.set_status("G-Code-Erzeugung abgebrochen – bitte DXF laden.")
                return

        header = self._collect_header()
        params = self._collect_params()
        if header is None or params is None:
            return
        post = create_postprocessor(self.var_post.get())

        if self._dxf_content is not None:
            code, warnings = generate_gcode(
                dxf=self._dxf_content,
                post=post,
                header=header,
                params=params,
                check_collisions=self.var_check_collisions.get(),
            )
            # deutlich machen, dass es echte Daten sind
            self.set_status("G-Code aus DXF erzeugt (echte Konturen).")
        else:
            code, warnings = self._generate_demo_gcode(
                post, header, params,
                check_collisions=self.var_check_collisions.get())
            self.set_status("DEMO-G-Code erzeugt – NICHT für die Maschine!")

        self._last_warnings = warnings
        self.txt_preview.delete("1.0", "end")
        self.txt_preview.insert("1.0", code)
        self._highlight_warning_lines(warnings)

        if any(w.severity == "kritisch" for w in warnings):
            self._show_warnings(warnings)

    def _highlight_warning_lines(self, warnings) -> None:
        self.txt_preview.tag_configure("crit",
            background="#5a0000", foreground="#ffdddd")
        self.txt_preview.tag_configure("warn",
            background="#5a3a00", foreground="#fff2cc")
        for w in warnings:
            tag = "crit" if w.severity == "kritisch" else "warn"
            self.txt_preview.tag_add(tag, f"{w.line_no}.0", f"{w.line_no}.end")

    def _show_warnings(self, warnings) -> None:
        top = tk.Toplevel(self)
        top.title("⚠ Sicherheitshinweise")
        top.geometry("720x420")
        top.transient(self)

        ttk.Label(top, text="Kritische G0-Bewegungen erkannt",
                  font=("", 11, "bold")).pack(anchor="w", padx=10, pady=6)

        txt = tk.Text(top, wrap="word", font=("Consolas", 9),
                      bg="#1e1e1e", fg="#ff8888")
        txt.pack(fill="both", expand=True, padx=10, pady=6)
        for w in warnings:
            txt.insert("end", w.short() + "\n")
        txt.config(state="disabled")

        ttk.Button(top, text="Verstanden", command=top.destroy).pack(pady=6)

    def _generate_demo_gcode(self, post, header, params,
                             check_collisions: bool = True):
        from dxf_loader import DxfContent, Contour, Hole
        import numpy as np
        square = Contour(
            points=np.array([[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]],
                            dtype=float),
            layer="DEMO", closed=True)
        hole = Hole(x=50, y=50, diameter=10, layer="DEMO")
        dxf = DxfContent(contours=[square], holes=[hole])
        return generate_gcode(
            dxf=dxf, post=post, header=header, params=params,
            check_collisions=check_collisions)

    def _on_save_gcode(self) -> None:
        content = self.txt_preview.get("1.0", "end").strip()
        if not content:
            messagebox.showinfo("Kein G-Code",
                                "Bitte zuerst G-Code generieren.")
            return

        post = create_postprocessor(self.var_post.get())
        ext = post.extension
        path = filedialog.asksaveasfilename(
            title="G-Code speichern",
            defaultextension=ext,
            filetypes=[(post.label, f"*{ext}"),
                       ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content + "\n")
            self.set_status(f"Gespeichert: {os.path.basename(path)}")
        except OSError as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc))

    # ==================================================================
    # Status
    # ==================================================================
    def set_status(self, message: str) -> None:
        """Wird vom Viewer oder intern aufgerufen, um Meldungen anzuzeigen."""
        if hasattr(self, "_status_var"):
            self._status_var.set(message)
        else:
            print(f"[status] {message}")


# ======================================================================
# Einstiegspunkt
# ======================================================================
def run() -> None:
    CamApp().mainloop()


if __name__ == "__main__":
    run()