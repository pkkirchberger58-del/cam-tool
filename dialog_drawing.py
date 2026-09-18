"""
dialog_drawing.py
-----------------
Dialog zum Erzeugen einer bemaßten technischen Zeichnung.

Modi:
- top:     Nur Draufsicht (kompakt)
- three:   Draufsicht + Front + Seite
- iso:     Draufsicht + Iso
- all:     Alles auf einer Seite
- multi:   Multi-Page-Bericht (empfohlen für komplexe Teile)
           → pro Ansicht eine Seite
           → Papierformat A1-A4 wählbar
           → Z-Überhöhung möglich

Nutzt:
- drawing.py         (für die Modi top/three/iso/all)
- drawing_multi.py   (für multi)
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from drawing import create_drawing, DrawingParams
from drawing_multi import create_report, MultiPageConfig


# --------------------------------------------------------------------------- #
# Modus-Hilfen
# --------------------------------------------------------------------------- #

MODE_HINTS = {
    "top":   "top   = nur Draufsicht (kompakt, A4)",
    "three": "three = Draufsicht + Front + Seite (A3)",
    "iso":   "iso   = Draufsicht + Iso (A3)",
    "all":   "all   = Alles auf einer Seite (A3)",
    "multi": "multi = Mehrseitiger Bericht (empfohlen!)",
}

PAGE_FORMATS = ["A1", "A2", "A3", "A4"]


class DrawingDialog(tk.Toplevel):
    """Modaler Dialog zum Erzeugen einer bemaßten Zeichnung."""

    def __init__(self, master, app_state, tools_db) -> None:
        super().__init__(master)
        self.title("Bemaßte Zeichnung erzeugen")
        self.geometry("620x720")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        self._app_state = app_state
        self._tools_db = tools_db
        self._result_path: str | None = None

        self._build_ui()

        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        # Header
        header = ttk.Frame(self, padding=(15, 12, 15, 6))
        header.pack(fill="x")

        ttk.Label(header, text="Bemaßte technische Zeichnung",
                  font=("", 13, "bold")).pack(anchor="w")

        ttk.Label(header,
                  text="Erzeugt aus der geladenen DXF eine bemaßte "
                       "Zeichnung als PDF.",
                  foreground="#666").pack(anchor="w", pady=(4, 0))

        # Info: geladene DXF
        info_frame = ttk.LabelFrame(self, text="Geladene Zeichnung",
                                     padding=10)
        info_frame.pack(fill="x", padx=15, pady=(10, 6))

        if self._app_state.has_dxf():
            content = self._app_state.dxf_content
            name = os.path.basename(self._app_state.dxf_path or "?")
            ttk.Label(info_frame, text=f"✓ {name}",
                      foreground="#2e7d32",
                      font=("", 10, "bold")).pack(anchor="w")
            ttk.Label(info_frame,
                      text=f"{len(content.contours)} Konturen · "
                           f"{len(content.holes)} Kreise · "
                           f"Einheit: {content.units}").pack(anchor="w",
                                                             pady=(3, 0))
        else:
            ttk.Label(info_frame, text="✗ Keine DXF geladen",
                      foreground="#c62828",
                      font=("", 10, "bold")).pack(anchor="w")
            ttk.Label(info_frame,
                      text="Bitte zuerst eine DXF laden, dann erneut öffnen.",
                      foreground="#666").pack(anchor="w", pady=(3, 0))

        # Parameter
        params_frame = ttk.LabelFrame(self, text="Parameter", padding=10)
        params_frame.pack(fill="x", padx=15, pady=6)

        self._add_row(params_frame, 0, "Programmnummer:", "1000")
        self._add_row(params_frame, 1, "Programmname:",   "TEIL_1")
        self._add_row(params_frame, 2, "Rohteilhöhe Z (mm):", "20")
        self._add_row(params_frame, 3, "Gesamttiefe Z (mm):",  "-5")

        # Zeichnungsmodus
        mode_frame = ttk.Frame(params_frame)
        mode_frame.grid(row=4, column=0, columnspan=2,
                        sticky="w", pady=(10, 0))
        ttk.Label(mode_frame, text="Zeichnungsmodus:").pack(side="left")
        self.var_mode = tk.StringVar(value="multi")
        mode_combo = ttk.Combobox(
            mode_frame, textvariable=self.var_mode,
            values=["top", "three", "iso", "all", "multi"],
            state="readonly", width=20)
        mode_combo.pack(side="left", padx=8)

        # Modus-Erklärung
        self._mode_hint = ttk.Label(
            params_frame,
            text=MODE_HINTS["multi"],
            foreground="#666", font=("", 9, "italic"))
        self._mode_hint.grid(row=5, column=0, columnspan=2,
                             sticky="w", pady=(3, 0))

        mode_combo.bind("<<ComboboxSelected>>",
                        lambda e: self._update_mode_hint())

        # Multi-Page-Optionen (nur bei "multi")
        self._multi_frame = ttk.LabelFrame(self,
                                            text="Multi-Page-Optionen",
                                            padding=10)
        self._multi_frame.pack(fill="x", padx=15, pady=6)
        self._build_multi_options(self._multi_frame)
        self._update_multi_visibility()

        # Ausgabeformat
        out_frame = ttk.LabelFrame(self, text="Ausgabe", padding=10)
        out_frame.pack(fill="x", padx=15, pady=6)

        fmt_row = ttk.Frame(out_frame)
        fmt_row.pack(fill="x")

        ttk.Label(fmt_row, text="Format:").pack(side="left")
        self.var_format = tk.StringVar(value="pdf")
        ttk.Radiobutton(fmt_row, text="PDF", value="pdf",
                        variable=self.var_format).pack(side="left", padx=6)
        ttk.Radiobutton(fmt_row, text="PNG", value="png",
                        variable=self.var_format).pack(side="left")

        # Buttons
        btn_frame = ttk.Frame(self, padding=(15, 10, 15, 15))
        btn_frame.pack(fill="x", side="bottom")

        self._btn_create = ttk.Button(
            btn_frame, text="Zeichnung erzeugen …",
            command=self._on_create)
        self._btn_create.pack(side="right", padx=4)

        ttk.Button(btn_frame, text="Abbrechen",
                   command=self.destroy).pack(side="right", padx=4)

        # Deaktivieren, wenn keine DXF
        if not self._app_state.has_dxf():
            self._btn_create.config(state="disabled")

    def _add_row(self, parent, row: int, label: str, default: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0,
                                            sticky="w", pady=3)
        var = tk.StringVar(value=default)
        ttk.Entry(parent, textvariable=var, width=20)\
            .grid(row=row, column=1, sticky="ew", pady=3)
        parent.columnconfigure(1, weight=1)

        if not hasattr(self, "_vars"):
            self._vars = {}
        key = label.rstrip(":").lower().replace(" ", "_")
        self._vars[key] = var

    def _build_multi_options(self, parent) -> None:
        """Optionen für den Multi-Page-Bericht."""
        # Papierformat
        row1 = ttk.Frame(parent)
        row1.pack(fill="x", pady=4)
        ttk.Label(row1, text="Papierformat:", width=18, anchor="w")\
            .pack(side="left")
        self.var_page = tk.StringVar(value="A3")
        ttk.Combobox(row1, textvariable=self.var_page,
                     values=PAGE_FORMATS, state="readonly",
                     width=10).pack(side="left", padx=6)

        # Ausrichtung
        row2 = ttk.Frame(parent)
        row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="Ausrichtung:", width=18, anchor="w")\
            .pack(side="left")
        self.var_orient = tk.StringVar(value="landscape")
        ttk.Radiobutton(row2, text="Quer", value="landscape",
                        variable=self.var_orient).pack(side="left")
        ttk.Radiobutton(row2, text="Hoch", value="portrait",
                        variable=self.var_orient).pack(side="left", padx=8)

        # Seiten-Auswahl
        row3 = ttk.Frame(parent)
        row3.pack(fill="x", pady=4)
        ttk.Label(row3, text="Seiten:", width=18, anchor="w")\
            .pack(side="left")

        cb_frame = ttk.Frame(row3)
        cb_frame.pack(side="left")

        self.var_inc_front = tk.BooleanVar(value=True)
        self.var_inc_side = tk.BooleanVar(value=True)
        self.var_inc_iso = tk.BooleanVar(value=True)
        self.var_inc_holes = tk.BooleanVar(value=True)

        ttk.Checkbutton(cb_frame, text="Front",
                        variable=self.var_inc_front)\
            .pack(side="left")
        ttk.Checkbutton(cb_frame, text="Seite",
                        variable=self.var_inc_side)\
            .pack(side="left", padx=6)
        ttk.Checkbutton(cb_frame, text="Iso",
                        variable=self.var_inc_iso)\
            .pack(side="left", padx=6)
        ttk.Checkbutton(cb_frame, text="Bohrungen",
                        variable=self.var_inc_holes)\
            .pack(side="left", padx=6)

        # Z-Überhöhung
        row4 = ttk.Frame(parent)
        row4.pack(fill="x", pady=(10, 4))

        self.var_z_scale = tk.BooleanVar(value=False)
        ttk.Checkbutton(row4,
                        text="Z-Überhöhung in Front-/Seitenansicht (3×)",
                        variable=self.var_z_scale)\
            .pack(anchor="w")

        ttk.Label(parent,
                  text="  → bei dünnen Bauteilen besser sichtbar",
                  foreground="#666",
                  font=("", 9, "italic")).pack(anchor="w", padx=20)

        # Detail-Seiten
        row5 = ttk.Frame(parent)
        row5.pack(fill="x", pady=(10, 0))

        self.var_auto_detail = tk.BooleanVar(value=False)
        ttk.Checkbutton(row5,
                        text="Detail-Seiten automatisch "
                             "(bei Teilen > 500 mm)",
                        variable=self.var_auto_detail)\
            .pack(anchor="w")

    def _update_mode_hint(self) -> None:
        mode = self.var_mode.get()
        self._mode_hint.config(text=MODE_HINTS.get(mode, ""))
        self._update_multi_visibility()

    def _update_multi_visibility(self) -> None:
        """Blendet Multi-Page-Optionen ein/aus."""
        mode = self.var_mode.get()
        if mode == "multi":
            self._multi_frame.pack(fill="x", padx=15, pady=6,
                                   before=self._multi_frame.master.winfo_children()[-1])
            # Einfacher: einfach wieder einpacken
            self._multi_frame.pack(fill="x", padx=15, pady=6)
        else:
            self._multi_frame.pack_forget()

    # ------------------------------------------------------------------ #
    # Zeichnung erzeugen
    # ------------------------------------------------------------------ #

    def _on_create(self) -> None:
        if not self._app_state.has_dxf():
            messagebox.showwarning(
                "Keine Zeichnung",
                "Bitte zuerst eine DXF-Datei laden.", parent=self)
            return

        # Parameter sammeln
        try:
            prog_number = self._vars["programmnummer"].get().strip() or "1000"
            prog_name = self._vars["programmname"].get().strip() or "TEIL"
            stock_height = float(
                self._vars["rohteilhöhe_z_(mm)"].get().replace(",", "."))
            depth = float(
                self._vars["gesamttiefe_z_(mm)"].get().replace(",", "."))
        except (ValueError, KeyError) as exc:
            messagebox.showerror(
                "Ungültige Eingabe",
                f"Bitte Zahlen prüfen:\n{exc}", parent=self)
            return

        mode = self.var_mode.get()
        fmt = self.var_format.get()

        # Bei Multi-Page: Nur PDF erlaubt
        if mode == "multi" and fmt != "pdf":
            messagebox.showwarning(
                "Nur PDF",
                "Der Multi-Page-Bericht wird nur als PDF unterstützt.",
                parent=self)
            self.var_format.set("pdf")
            return

        # Datei-Ziel erfragen
        ext = ".pdf" if (fmt == "pdf" or mode == "multi") else ".png"
        default_name = prog_name

        path = filedialog.asksaveasfilename(
            parent=self,
            title="Zeichnung speichern unter…",
            initialdir=getattr(self._app_state, "last_save_dir", "") or None,
            initialfile=f"{default_name}_Zeichnung{ext}",
            defaultextension=ext,
            filetypes=[("PDF-Datei", "*.pdf")] if fmt == "pdf"
                      else [("PNG-Bild", "*.png"),
                            ("Alle Dateien", "*.*")])
        if not path:
            return

        # Werkzeug aus DB (erstes Werkzeug als Default)
        tool_name = "–"
        tool_diameter = 0.0
        if self._tools_db.tools:
            t0 = self._tools_db.tools[0]
            tool_name = t0.name
            tool_diameter = t0.diameter

        # Zeichnungsparameter
        params = DrawingParams(
            program_name=prog_name,
            program_number=prog_number,
            tool_name=tool_name,
            tool_diameter=tool_diameter,
            total_depth=depth,
            stock_height=stock_height,
            post_name="Sinumerik 840D",
            units=self._app_state.dxf_content.units or "mm",
        )

        # Konturen + Bohrungen übergeben
        contours = [c.points for c in self._app_state.dxf_content.contours]
        holes = [(h.x, h.y, h.diameter)
                 for h in self._app_state.dxf_content.holes]

        # Zeichnung erzeugen
        try:
            self._btn_create.config(state="disabled", text="Erzeuge …")
            self.update()

            if mode == "multi":
                # Multi-Page-Bericht
                saved = create_report(
                    contours, holes, path, params,
                    page_format=self.var_page.get(),
                    orientation=self.var_orient.get(),
                    include_front=self.var_inc_front.get(),
                    include_side=self.var_inc_side.get(),
                    include_iso=self.var_inc_iso.get(),
                    include_hole_list=self.var_inc_holes.get(),
                    auto_detail=self.var_auto_detail.get(),
                )
            else:
                # Standard-Modus
                saved = create_drawing(contours, holes, path,
                                       params, mode=mode)

        except Exception as exc:
            self._btn_create.config(state="normal",
                                    text="Zeichnung erzeugen …")
            import traceback
            traceback.print_exc()
            messagebox.showerror(
                "Zeichnung fehlgeschlagen",
                f"Konnte Zeichnung nicht erzeugen:\n{exc}", parent=self)
            return

        self._result_path = saved

        # Speicherordner merken
        try:
            self._app_state.last_save_dir = os.path.dirname(saved)
        except AttributeError:
            pass

        # Erfolg melden
        answer = messagebox.askyesno(
            "Zeichnung erstellt",
            f"Gespeichert:\n{os.path.basename(saved)}\n\n"
            f"Jetzt öffnen?", parent=self)

        if answer:
            self._open_file(saved)

        self.destroy()

    @staticmethod
    def _open_file(path: str) -> None:
        """Öffnet eine Datei mit dem System-Default."""
        try:
            os.startfile(path)
        except AttributeError:
            import subprocess
            import sys
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, path])


# --------------------------------------------------------------------------- #
# Bequeme Funktion
# --------------------------------------------------------------------------- #

def open_drawing_dialog(master, app_state, tools_db) -> str | None:
    """
    Öffnet den Zeichnungs-Dialog modal.

    Rückgabe: Pfad der erzeugten Datei (oder None bei Abbruch).
    """
    dlg = DrawingDialog(master, app_state, tools_db)
    master.wait_window(dlg)
    return dlg._result_path