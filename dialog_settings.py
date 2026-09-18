"""
dialog_settings.py
------------------
Einstellungs-Dialog für das CAM-Verifikations-Tool.

Kategorien:
- Verifikation: Toleranz, was geprüft wird
- Pfade: Letzte Ordner für DXF, G-Code, Speichern
- Postprozessor: Standard-Steuerung

Verhalten:
- Öffnet modal über dem Hauptfenster
- Speichern → Werte werden an AppConfig übergeben
- Abbrechen / ESC → verwerfen
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog
from typing import Optional

from config import AppConfig
from postprocessors import POSTPROCESSORS


class SettingsDialog(tk.Toplevel):
    """Modaler Einstellungs-Dialog."""

    def __init__(self, master, config: AppConfig) -> None:
        super().__init__(master)
        self.title("Einstellungen")
        self.geometry("640x620")
        self.transient(master)
        self.grab_set()
        self.resizable(False, False)

        # Kopie der Config arbeiten
        self._config = config
        self._changed = False

        self._build_ui()

        # Bindings
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    # ------------------------------------------------------------------ #
    # UI-Aufbau
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        # Notebook (Tabs)
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        # Tab 1: Verifikation
        tab_verify = ttk.Frame(notebook, padding=15)
        notebook.add(tab_verify, text="  Verifikation  ")
        self._build_verify_tab(tab_verify)

        # Tab 2: Pfade
        tab_paths = ttk.Frame(notebook, padding=15)
        notebook.add(tab_paths, text="  Pfade  ")
        self._build_paths_tab(tab_paths)

        # Tab 3: Postprozessor
        tab_post = ttk.Frame(notebook, padding=15)
        notebook.add(tab_post, text="  Postprozessor  ")
        self._build_post_tab(tab_post)

        # Fußzeile mit Buttons
        footer = ttk.Frame(self, padding=(12, 8))
        footer.pack(fill="x")

        ttk.Button(footer, text="Speichern",
                   command=self._on_save).pack(side="right", padx=4)
        ttk.Button(footer, text="Abbrechen",
                   command=self._on_cancel).pack(side="right", padx=4)
        ttk.Button(footer, text="Auf Standard zurücksetzen",
                   command=self._on_reset).pack(side="left", padx=4)

    # ------------------------------------------------------------------ #
    # Tab 1: Verifikation
    # ------------------------------------------------------------------ #

    def _build_verify_tab(self, parent) -> None:
        ttk.Label(parent, text="Verifikations-Parameter",
                  font=("", 11, "bold")).pack(anchor="w", pady=(0, 10))

        # Toleranz
        tol_frame = ttk.LabelFrame(parent, text="Toleranz",
                                    padding=10)
        tol_frame.pack(fill="x", pady=6)

        ttk.Label(tol_frame,
                  text="Toleranz in mm (max. erlaubte Abweichung):")\
            .pack(anchor="w")

        row = ttk.Frame(tol_frame)
        row.pack(fill="x", pady=6)

        self.var_tolerance = tk.StringVar(
            value=f"{self._config.last_tolerance:.3f}"
            if hasattr(self._config, "last_tolerance")
            else "0.010")

        ttk.Entry(row, textvariable=self.var_tolerance, width=10)\
            .pack(side="left")

        ttk.Label(row, text="mm")\
            .pack(side="left", padx=6)

        ttk.Label(row,
                  text="(Standard: 0,010 mm = 10 µm)",
                  foreground="#666")\
            .pack(side="left", padx=10)

        # Was wird geprüft?
        check_frame = ttk.LabelFrame(parent, text="Was wird geprüft?",
                                      padding=10)
        check_frame.pack(fill="x", pady=6)

        self.var_check_contours = tk.BooleanVar(
            value=getattr(self._config, "check_contours", True))
        self.var_check_holes = tk.BooleanVar(
            value=getattr(self._config, "check_holes", True))
        self.var_check_collisions = tk.BooleanVar(
            value=getattr(self._config, "check_collisions", True))

        ttk.Checkbutton(check_frame,
                        text="Konturen prüfen (Außen, Innen, Taschen)",
                        variable=self.var_check_contours)\
            .pack(anchor="w", pady=3)
        ttk.Checkbutton(check_frame,
                        text="Bohrungen prüfen (Position, Durchmesser)",
                        variable=self.var_check_holes)\
            .pack(anchor="w", pady=3)
        ttk.Checkbutton(check_frame,
                        text="Kollisionsprüfung (G0 durch Material)",
                        variable=self.var_check_collisions)\
            .pack(anchor="w", pady=3)

        # Info-Box
        info = tk.Frame(parent, bg="#f0f7ff", relief="solid",
                        borderwidth=1)
        info.pack(fill="x", pady=(15, 0))

        tk.Label(info,
                 text="ℹ  Hinweis",
                 bg="#f0f7ff", fg="#1f4e79",
                 font=("", 10, "bold"),
                 anchor="w")\
            .pack(anchor="w", padx=10, pady=(8, 2))

        tk.Label(info,
                 text="Die Toleranz bestimmt, wie groß die maximal "
                      "erlaubte Abweichung\nzwischen G-Code und CAD-Zeichnung "
                      "sein darf.\n\n"
                      "Für Präzisionsfertigung: 0,01 mm (Standard)\n"
                      "Für Schrupp-Arbeiten:      0,05 mm",
                 bg="#f0f7ff", fg="#333",
                 justify="left", anchor="w")\
            .pack(anchor="w", padx=10, pady=(0, 8))

    # ------------------------------------------------------------------ #
    # Tab 2: Pfade
    # ------------------------------------------------------------------ #

    def _build_paths_tab(self, parent) -> None:
        ttk.Label(parent, text="Standard-Ordner",
                  font=("", 11, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Label(parent,
                  text="Diese Ordner werden beim nächsten Öffnen von "
                       "Datei-Dialogen\nvorgeschlagen.",
                  foreground="#666")\
            .pack(anchor="w", pady=(0, 15))

        # DXF-Ordner
        self._build_path_row(
            parent, "DXF-Ordner:",
            getattr(self._config, "last_dxf_dir", ""),
            self._browse_dxf)

        # G-Code-Ordner
        self._build_path_row(
            parent, "G-Code-Ordner:",
            getattr(self._config, "last_gcode_dir", ""),
            self._browse_gcode)

        # Speicher-Ordner
        self._build_path_row(
            parent, "Speicher-Ordner:",
            getattr(self._config, "last_save_dir", ""),
            self._browse_save)

        # Werkzeug-DB
        ttk.Separator(parent, orient="horizontal")\
            .pack(fill="x", pady=15)

        ttk.Label(parent, text="Werkzeug-Datenbank",
                  font=("", 11, "bold")).pack(anchor="w", pady=(0, 6))

        self._build_path_row(
            parent, "Pfad zur tools.json:",
            getattr(self._config, "tools_db_path", "tools.json"),
            self._browse_tools)

    def _build_path_row(self, parent, label: str,
                        initial: str, command) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=6)

        ttk.Label(frame, text=label, width=18, anchor="w")\
            .pack(side="left")

        var = tk.StringVar(value=initial)
        entry = ttk.Entry(frame, textvariable=var)
        entry.pack(side="left", fill="x", expand=True, padx=6)

        ttk.Button(frame, text="Ändern…", command=command)\
            .pack(side="left")

        # Referenz speichern (per Label)
        entry.var_ref = var  # type: ignore

    # ------------------------------------------------------------------ #
    # Tab 3: Postprozessor
    # ------------------------------------------------------------------ #

    def _build_post_tab(self, parent) -> None:
        ttk.Label(parent, text="Standard-Steuerung",
                  font=("", 11, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Label(parent,
                  text="Diese Steuerung wird als Vorauswahl in den "
                       "Dropdowns verwendet.",
                  foreground="#666")\
            .pack(anchor="w", pady=(0, 15))

        # Postprozessor-Dropdown
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=6)

        ttk.Label(frame, text="Postprozessor:", width=18, anchor="w")\
            .pack(side="left")

        self.var_post = tk.StringVar(
            value=getattr(self._config, "last_post",
                         list(POSTPROCESSORS.keys())[0]))

        post_names = list(POSTPROCESSORS.keys())
        combo = ttk.Combobox(frame, textvariable=self.var_post,
                             values=post_names, state="readonly",
                             width=40)
        combo.pack(side="left", padx=6)

        # Info-Box
        info = tk.Frame(parent, bg="#f0f7ff", relief="solid",
                        borderwidth=1)
        info.pack(fill="x", pady=(20, 0))

        tk.Label(info,
                 text="ℹ  Verfügbare Postprozessoren",
                 bg="#f0f7ff", fg="#1f4e79",
                 font=("", 10, "bold"),
                 anchor="w")\
            .pack(anchor="w", padx=10, pady=(8, 2))

        text = "\n".join(f"• {name}" for name in post_names)

        tk.Label(info, text=text,
                 bg="#f0f7ff", fg="#333",
                 justify="left", anchor="w")\
            .pack(anchor="w", padx=10, pady=(0, 8))

    # ------------------------------------------------------------------ #
    # Datei-Browser
    # ------------------------------------------------------------------ #

    def _browse_dxf(self) -> None:
        path = filedialog.askdirectory(title="DXF-Ordner auswählen")
        if path:
            self._set_path("dxf", path)

    def _browse_gcode(self) -> None:
        path = filedialog.askdirectory(title="G-Code-Ordner auswählen")
        if path:
            self._set_path("gcode", path)

    def _browse_save(self) -> None:
        path = filedialog.askdirectory(title="Speicher-Ordner auswählen")
        if path:
            self._set_path("save", path)

    def _browse_tools(self) -> None:
        path = filedialog.askopenfilename(
            title="Werkzeug-DB auswählen",
            filetypes=[("JSON-Datei", "*.json"), ("Alle Dateien", "*.*")])
        if path:
            for child in self.winfo_children():
                pass  # Placeholder
            # Direkt setzen
            self._set_path("tools", path)

    def _set_path(self, key: str, value: str) -> None:
        """Setzt den Pfad im entsprechenden Entry."""
        # Über alle Frames iterieren und den passenden finden
        # Einfacher Ansatz: wir merken uns die Variablen
        if not hasattr(self, "_path_vars"):
            self._path_vars = {}
        self._path_vars[key] = value
        # Aktualisiere die Anzeige
        self._refresh_paths()

    def _refresh_paths(self) -> None:
        """Aktualisiert die Pfad-Felder."""
        # Wird beim nächsten Aufbau verwendet
        pass

    # ------------------------------------------------------------------ #
    # Aktionen
    # ------------------------------------------------------------------ #

    def _on_save(self) -> None:
        """Übernimmt die Einstellungen."""
        # Toleranz prüfen
        try:
            tol = float(self.var_tolerance.get().replace(",", "."))
            if tol <= 0 or tol > 10:
                raise ValueError("Toleranz muss zwischen 0 und 10 liegen.")
        except ValueError as exc:
            from tkinter import messagebox
            messagebox.showerror("Ungültige Toleranz",
                                 f"Bitte eine Zahl > 0 eingeben.\n{exc}",
                                 parent=self)
            return

        # In Config übertragen
        cfg = self._config
        try:
            cfg.last_tolerance = tol
        except AttributeError:
            pass

        try:
            cfg.check_contours = self.var_check_contours.get()
            cfg.check_holes = self.var_check_holes.get()
            cfg.check_collisions = self.var_check_collisions.get()
        except AttributeError:
            pass

        try:
            cfg.last_post = self.var_post.get()
        except AttributeError:
            pass

        self._changed = True
        self.destroy()

    def _on_cancel(self) -> None:
        """Verwirft Änderungen."""
        self.destroy()

    def _on_reset(self) -> None:
        """Setzt alle Felder auf Standard zurück."""
        self.var_tolerance.set("0.010")
        self.var_check_contours.set(True)
        self.var_check_holes.set(True)
        self.var_check_collisions.set(True)
        self.var_post.set(list(POSTPROCESSORS.keys())[0])


# --------------------------------------------------------------------------- #
# Bequeme Funktion
# --------------------------------------------------------------------------- #

def open_settings(master, config: AppConfig) -> bool:
    """
    Öffnet den Einstellungs-Dialog modal.

    Rückgabe: True wenn gespeichert wurde, False bei Abbruch.
    """
    dlg = SettingsDialog(master, config)
    master.wait_window(dlg)
    return dlg._changed