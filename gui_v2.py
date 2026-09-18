"""
gui_v2.py
---------
CAM-Verifikations-Tool – Neue GUI mit Dashboard + Workflow.

Layout:
- Dashboard (Start): Große Kacheln, letzte Prüfungen
- Workflow: Schritt 1-2-3 (Zeichnung, G-Code, Prüfen)
- Ergebnis: Ampel, Details, 3D-Ansicht, PDF-Export

Drag & Drop: DXF- und G-Code-Dateien können ins Fenster gezogen werden.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

# Drag & Drop (optional)
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False
    print("[gui_v2] Hinweis: tkinterdnd2 nicht installiert. "
          "Drag & Drop deaktiviert.")
    print("[gui_v2] Installation: pip install tkinterdnd2")

from app_state import AppState
from history import History, HistoryEntry
from config import AppConfig
from tools_db import ToolDatabase

from dxf_loader import load_dxf
from gcode_parser import parse_file
from compare import verify, CompareConfig

# Dialoge (NEU)
from dialog_settings import open_settings
from dialog_drawing import open_drawing_dialog
from dialog_tools import open_tools_dialog


from viewer3d import STLViewer


# --------------------------------------------------------------------------- #
# Basisklasse (mit oder ohne Drag&Drop)
# --------------------------------------------------------------------------- #

if HAS_DND:
    BaseTk = TkinterDnD.Tk
else:
    BaseTk = tk.Tk


# --------------------------------------------------------------------------- #
# Farben und Styles
# --------------------------------------------------------------------------- #

COLOR_BG = "#f5f5f5"
COLOR_CARD = "#ffffff"
COLOR_CARD_HOVER = "#e8f0fe"
COLOR_HEADER = "#1f4e79"
COLOR_TEXT = "#202020"
COLOR_TEXT_LIGHT = "#666666"
COLOR_OK = "#2e7d32"
COLOR_WARN = "#f9a825"
COLOR_FAIL = "#c62828"


# --------------------------------------------------------------------------- #
# Hauptfenster
# --------------------------------------------------------------------------- #

class CamAppV2(BaseTk):
    """Neue CAM-GUI mit Dashboard + Workflow."""

    APP_TITLE = "CAM-Verifikations-Tool"
    MIN_SIZE = (1100, 750)

    def __init__(self) -> None:
        super().__init__()
        self.title(self.APP_TITLE)
        self.geometry("1300x850")
        self.minsize(*self.MIN_SIZE)
        self.configure(bg=COLOR_BG)

        # Zustand
        self.state = AppState()
        self.history = History()
        self.config = AppConfig.load()
        self.tools_db = ToolDatabase(self.config.tools_db_path)

        # Theme
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")

        # Container für Ansichten
        self.container = tk.Frame(self, bg=COLOR_BG)
        self.container.pack(fill="both", expand=True)

        # Aktuelle Ansicht
        self._current_frame = None
        self._show_dashboard()

        # Drag & Drop aktivieren
        if HAS_DND:
            self._setup_dnd()

        # Fensterschließen
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    # Fenster-Management
    # ------------------------------------------------------------------ #

    def _clear_container(self) -> None:
        if self._current_frame is not None:
            self._current_frame.destroy()
            self._current_frame = None

    def _show_dashboard(self) -> None:
        self._clear_container()
        self.state.current_view = "dashboard"
        self._current_frame = DashboardFrame(self.container, self)
        self._current_frame.pack(fill="both", expand=True)

    def _show_workflow(self) -> None:
        self._clear_container()
        self.state.current_view = "workflow"
        self._current_frame = WorkflowFrame(self.container, self)
        self._current_frame.pack(fill="both", expand=True)

    def _show_result(self) -> None:
        self._clear_container()
        self.state.current_view = "result"
        self._current_frame = ResultFrame(self.container, self)
        self._current_frame.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ #
    # Drag & Drop
    # ------------------------------------------------------------------ #

    def _setup_dnd(self) -> None:
        """Registriert das Hauptfenster als Drop-Ziel."""
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event) -> None:
        """Wird aufgerufen, wenn Dateien ins Fenster gezogen werden."""
        # Datei-Pfade aus Event extrahieren
        files = self.tk.splitlist(event.data)
        if not files:
            return

        # Erste Datei verarbeiten
        path = files[0]
        # Klammern entfernen (kommen bei Windows manchmal mit)
        path = path.strip("{}")

        if not os.path.isfile(path):
            return

        ext = os.path.splitext(path)[1].lower()

        if ext == ".dxf":
            self._load_dxf_auto(path)
        elif ext in (".mpf", ".nc", ".h", ".i", ".txt"):
            self._load_gcode_auto(path)
        else:
            messagebox.showwarning(
                "Unbekannter Dateityp",
                f"Die Datei '{os.path.basename(path)}' hat einen "
                f"unbekannten Dateityp.\n\n"
                f"Erwartet: .dxf, .mpf, .nc, .h")

    def _load_dxf_auto(self, path: str) -> None:
        """Lädt DXF automatisch (nach Drop)."""
        try:
            content = load_dxf(path)
        except Exception as exc:
            messagebox.showerror("DXF-Fehler",
                                 f"Konnte DXF nicht lesen:\n{exc}")
            return

        self.state.dxf_path = path
        self.state.dxf_content = content
        self.state.last_dxf_dir = os.path.dirname(path)

        # Falls im Workflow → neu zeichnen
        if self.state.current_view == "workflow":
            self._show_workflow()
        else:
            self._show_workflow()
            if self.state.has_gcode():
                # Direkt zu Schritt 3 wenn schon G-Code geladen
                pass

    def _load_gcode_auto(self, path: str) -> None:
        """Lädt G-Code automatisch (nach Drop)."""
        try:
            result = parse_file(path)
        except Exception as exc:
            messagebox.showerror("G-Code-Fehler",
                                 f"Konnte G-Code nicht lesen:\n{exc}")
            return

        self.state.gcode_path = path
        self.state.gcode_result = result
        self.state.last_gcode_dir = os.path.dirname(path)

        # Neu zeichnen
        if self.state.current_view == "workflow":
            self._show_workflow()
        else:
            self._show_workflow()

    # ------------------------------------------------------------------ #
    # Aktionen (für Dashboard/Workflow)
    # ------------------------------------------------------------------ #

    def browse_dxf(self) -> None:
        path = filedialog.askopenfilename(
            title="DXF-Zeichnung auswählen",
            initialdir=self.state.last_dxf_dir or None,
            filetypes=[("DXF-Zeichnungen", "*.dxf"),
                       ("Alle Dateien", "*.*")])
        if path:
            self._load_dxf_auto(path)

    def browse_gcode(self) -> None:
        path = filedialog.askopenfilename(
            title="G-Code-Programm auswählen",
            initialdir=self.state.last_gcode_dir or None,
            filetypes=[("Sinumerik-Programm", "*.mpf"),
                       ("Heidenhain-Programm", "*.h"),
                       ("NC-Datei", "*.nc"),
                       ("Alle Dateien", "*.*")])
        if path:
            self._load_gcode_auto(path)

    def start_verification(self) -> None:
        """Startet die Verifikation im Hintergrund."""
        if not self.state.has_dxf():
            messagebox.showwarning("Keine Zeichnung",
                                   "Bitte zuerst eine DXF-Datei laden.")
            return
        if not self.state.has_gcode():
            messagebox.showwarning("Kein G-Code",
                                   "Bitte zuerst ein G-Code-Programm laden.")
            return

        # Fortschrittsdialog
        progress_win = tk.Toplevel(self)
        progress_win.title("Verifikation läuft…")
        progress_win.geometry("400x120")
        progress_win.transient(self)
        progress_win.grab_set()

        ttk.Label(progress_win, text="Prüfung läuft …",
                  font=("", 11)).pack(pady=20)
        progress = ttk.Progressbar(progress_win, mode="indeterminate",
                                   length=350)
        progress.pack(pady=10)
        progress.start(10)

        def run_verify():
            try:
                config = CompareConfig(
                    tolerance=self.state.tolerance,
                    arc_resolution=0.05,
                    hole_min_diameter=1.0,
                    hole_max_diameter=200.0,
                )
                result = verify(self.state.dxf_content,
                                self.state.gcode_result,
                                config)

                # Historie
                status = "OK" if result.total_fail == 0 else "FEHLER"
                entry = HistoryEntry(
                    datum=History.now_str(),
                    dxf=os.path.basename(self.state.dxf_path or ""),
                    gcode=os.path.basename(self.state.gcode_path or ""),
                    ergebnis=status,
                    elemente=result.total_elements,
                    fehler=result.total_fail,
                    max_abw=result.max_distance_overall,
                    toleranz=self.state.tolerance,
                )
                self.history.add(entry)

                # Aufruf im Main-Thread
                self.after(0, self._on_verify_done, result, progress_win)

            except Exception as exc:
                self.after(0, self._on_verify_error, exc, progress_win)

        threading.Thread(target=run_verify, daemon=True).start()

    def _on_verify_done(self, result, progress_win) -> None:
        progress_win.destroy()
        self.state.verify_result = result
        self._show_result()

    def _on_verify_error(self, exc, progress_win) -> None:
        progress_win.destroy()
        messagebox.showerror("Verifikation fehlgeschlagen",
                             f"Fehler:\n{exc}")

    def reset(self) -> None:
        """Setzt alles zurück (neue Prüfung)."""
        self.state.reset()
        self._show_dashboard()

    # ------------------------------------------------------------------ #
    # Fensterschließen
    # ------------------------------------------------------------------ #

    def _on_close(self) -> None:
        try:
            self.config.save()
        except Exception:
            pass
        self.destroy()


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #

class DashboardFrame(tk.Frame):
    """Start-Ansicht mit Kacheln."""

    def __init__(self, master, app: CamAppV2) -> None:
        super().__init__(master, bg=COLOR_BG)
        self.app = app
        self._build()

    def _build(self) -> None:
        # Header
        header = tk.Frame(self, bg=COLOR_HEADER, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="CAM-Verifikations-Tool",
                 bg=COLOR_HEADER, fg="white",
                 font=("Segoe UI", 20, "bold")).pack(side="left",
                                                     padx=30, pady=20)

        # Kachel-Bereich
        main = tk.Frame(self, bg=COLOR_BG)
        main.pack(fill="both", expand=True, padx=40, pady=20)

        tk.Label(main, text="Was möchtest du tun?",
                 bg=COLOR_BG, fg=COLOR_TEXT,
                 font=("Segoe UI", 14)).pack(anchor="w", pady=(0, 15))

        # Grid mit Kacheln
        grid = tk.Frame(main, bg=COLOR_BG)
        grid.pack(fill="x")

        # Kachel 1: Neue Prüfung
        self._make_tile(
            grid, 0, 0,
            "🎯", "NEUE PRÜFUNG",
            "DXF + G-Code vergleichen",
            self.app._show_workflow)

        # Kachel 2: Zeichnung erstellen
        self._make_tile(
            grid, 0, 1,
            "📄", "ZEICHNUNG",
            "Bemaßte Ansicht als PDF",
            self._on_drawing)

        # Kachel 3: Werkzeuge
        self._make_tile(
            grid, 1, 0,
            "🛠", "WERKZEUGE",
            "Fräser, Bohrer verwalten",
            self._on_tools)

        # Kachel 4: Einstellungen
        self._make_tile(
            grid, 1, 1,
            "⚙", "EINSTELLUNGEN",
            "Toleranz, Pfade konfigurieren",
            self._on_settings)

        # Historie
        self._build_history(main)

    def _make_tile(self, parent, row: int, col: int,
                   icon: str, title: str, subtitle: str,
                   command) -> None:
        card = tk.Frame(parent, bg=COLOR_CARD,
                        highlightbackground="#dddddd",
                        highlightthickness=1,
                        cursor="hand2")
        card.grid(row=row, column=col, padx=10, pady=10,
                  sticky="nsew", ipadx=20, ipady=20)

        # Klick-Bindung
        for w in [card]:
            w.bind("<Button-1>", lambda e: command())

        # Icon
        icon_lbl = tk.Label(card, text=icon, bg=COLOR_CARD,
                            font=("Segoe UI", 32))
        icon_lbl.pack(pady=(10, 5))
        icon_lbl.bind("<Button-1>", lambda e: command())

        # Titel
        title_lbl = tk.Label(card, text=title, bg=COLOR_CARD,
                             fg=COLOR_HEADER,
                             font=("Segoe UI", 13, "bold"))
        title_lbl.pack()
        title_lbl.bind("<Button-1>", lambda e: command())

        # Untertitel
        sub_lbl = tk.Label(card, text=subtitle, bg=COLOR_CARD,
                           fg=COLOR_TEXT_LIGHT,
                           font=("Segoe UI", 10))
        sub_lbl.pack(pady=(2, 10))
        sub_lbl.bind("<Button-1>", lambda e: command())

        parent.columnconfigure(col, weight=1)
        parent.rowconfigure(row, weight=1)

    def _build_history(self, parent) -> None:
        tk.Label(parent, text="Letzte Prüfungen:",
                 bg=COLOR_BG, fg=COLOR_TEXT,
                 font=("Segoe UI", 12)).pack(anchor="w",
                                             pady=(30, 5))

        hist_frame = tk.Frame(parent, bg=COLOR_CARD,
                              highlightbackground="#dddddd",
                              highlightthickness=1)
        hist_frame.pack(fill="both", expand=True)

        entries = self.app.history.get_recent(5)
        if not entries:
            tk.Label(hist_frame, text="Noch keine Prüfungen durchgeführt.",
                     bg=COLOR_CARD, fg=COLOR_TEXT_LIGHT,
                     font=("Segoe UI", 10, "italic")).pack(pady=20)
            return

        for e in entries:
            row = tk.Frame(hist_frame, bg=COLOR_CARD)
            row.pack(fill="x", padx=15, pady=4)

            # Ampel
            icon = "✅" if e.ergebnis == "OK" else "❌"
            color = COLOR_OK if e.ergebnis == "OK" else COLOR_FAIL

            tk.Label(row, text=icon, bg=COLOR_CARD,
                     font=("Segoe UI", 12)).pack(side="left")
            tk.Label(row, text=e.datum, bg=COLOR_CARD,
                     fg=COLOR_TEXT_LIGHT, width=15,
                     anchor="w").pack(side="left", padx=8)
            tk.Label(row, text=e.gcode, bg=COLOR_CARD,
                     fg=COLOR_TEXT, width=25,
                     anchor="w").pack(side="left")
            tk.Label(row, text=f"{e.elemente} Elemente",
                     bg=COLOR_CARD, fg=COLOR_TEXT_LIGHT,
                     anchor="w").pack(side="left", padx=8)
            info = f"{e.fehler} Fehler" if e.fehler else "OK"
            tk.Label(row, text=info, bg=COLOR_CARD, fg=color,
                     font=("Segoe UI", 10, "bold"),
                     anchor="w").pack(side="left", padx=8)

    def _on_drawing(self) -> None:
        """Öffnet den Zeichnungs-Generator-Dialog."""
        open_drawing_dialog(self.app, self.app.state, self.app.tools_db)

    def _on_tools(self) -> None:
        """Öffnet den Werkzeug-Editor."""
        open_tools_dialog(self.app, self.app.tools_db)

    def _on_settings(self) -> None:
        """Öffnet den Einstellungs-Dialog."""
        saved = open_settings(self.app, self.app.config)
        if saved:
            # Falls Einstellungen geändert wurden, ins GUI übernehmen
            if hasattr(self.app.config, "last_tolerance"):
                self.app.state.tolerance = self.app.config.last_tolerance


# --------------------------------------------------------------------------- #
# Workflow
# --------------------------------------------------------------------------- #

class WorkflowFrame(tk.Frame):
    """Schritt-für-Schritt-Ansicht."""

    def __init__(self, master, app: CamAppV2) -> None:
        super().__init__(master, bg=COLOR_BG)
        self.app = app
        self._build()

    def _build(self) -> None:
        # Header
        header = tk.Frame(self, bg=COLOR_HEADER, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Button(header, text="← Zurück", command=self.app._show_dashboard,
                  bg=COLOR_HEADER, fg="white", bd=0,
                  font=("Segoe UI", 11),
                  activebackground=COLOR_HEADER,
                  activeforeground="white",
                  cursor="hand2").pack(side="left", padx=20, pady=20)

        tk.Label(header, text="Neue Prüfung",
                 bg=COLOR_HEADER, fg="white",
                 font=("Segoe UI", 16, "bold")).pack(side="left")

        # Fortschrittsanzeige
        steps = tk.Frame(self, bg=COLOR_BG)
        steps.pack(fill="x", padx=40, pady=20)

        has_dxf = self.app.state.has_dxf()
        has_gcode = self.app.state.has_gcode()

        self._make_step(steps, 1, "Zeichnung", has_dxf,
                        "aktiv" if not has_dxf else "erledigt")
        self._make_step(steps, 2, "G-Code", has_gcode,
                        "aktiv" if has_dxf and not has_gcode
                        else ("erledigt" if has_gcode else ""))
        self._make_step(steps, 3, "Prüfen", False,
                        "aktiv" if has_dxf and has_gcode else "")

        # Inhalt
        content = tk.Frame(self, bg=COLOR_BG)
        content.pack(fill="both", expand=True, padx=40, pady=10)

        # Schritt 1
        self._build_step_dxf(content, has_dxf)

        # Schritt 2
        if has_dxf:
            self._build_step_gcode(content, has_gcode)

        # Schritt 3
        if has_dxf and has_gcode:
            self._build_step_verify(content)

    def _make_step(self, parent, num: int, label: str,
                   done: bool, state: str) -> None:
        frame = tk.Frame(parent, bg=COLOR_BG)
        frame.pack(side="left", padx=5)

        if done:
            icon = "✓"
            color = COLOR_OK
        elif state == "aktiv":
            icon = "●"
            color = COLOR_HEADER
        else:
            icon = "○"
            color = "#aaaaaa"

        tk.Label(frame, text=f"{icon}  Schritt {num}",
                 bg=COLOR_BG, fg=color,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(frame, text=label,
                 bg=COLOR_BG, fg=COLOR_TEXT_LIGHT,
                 font=("Segoe UI", 10)).pack(anchor="w")

        # Verbindungslinie
        tk.Label(parent, text="  ──────  ",
                 bg=COLOR_BG, fg="#cccccc",
                 font=("Segoe UI", 12)).pack(side="left")

    def _build_step_dxf(self, parent, done: bool) -> None:
        card = tk.Frame(parent, bg=COLOR_CARD,
                        highlightbackground="#dddddd",
                        highlightthickness=1)
        card.pack(fill="x", pady=8, ipady=15)

        if done:
            tk.Label(card, text="✅ Zeichnung geladen",
                     bg=COLOR_CARD, fg=COLOR_OK,
                     font=("Segoe UI", 12, "bold")).pack(anchor="w",
                                                          padx=20, pady=(5, 5))
            tk.Label(card, text=self.app.state.file_summary_dxf(),
                     bg=COLOR_CARD, fg=COLOR_TEXT,
                     font=("Segoe UI", 10)).pack(anchor="w", padx=20)
        else:
            tk.Label(card, text="📄 SCHRITT 1: Zeichnung laden",
                     bg=COLOR_CARD, fg=COLOR_HEADER,
                     font=("Segoe UI", 12, "bold")).pack(anchor="w",
                                                          padx=20, pady=(5, 5))
            tk.Label(card, text="Lade die DXF-Zeichnung des Kunden.",
                     bg=COLOR_CARD, fg=COLOR_TEXT_LIGHT,
                     font=("Segoe UI", 10)).pack(anchor="w", padx=20)

            btn_frame = tk.Frame(card, bg=COLOR_CARD)
            btn_frame.pack(fill="x", padx=20, pady=15)

            tk.Button(btn_frame, text="📁  DXF-Datei auswählen…",
                      command=self.app.browse_dxf,
                      bg=COLOR_HEADER, fg="white", bd=0,
                      padx=20, pady=10,
                      font=("Segoe UI", 11, "bold"),
                      cursor="hand2").pack(side="left")

            tk.Label(btn_frame,
                     text="oder Datei ins Fenster ziehen",
                     bg=COLOR_CARD, fg=COLOR_TEXT_LIGHT,
                     font=("Segoe UI", 9, "italic")).pack(side="left",
                                                          padx=15)

    def _build_step_gcode(self, parent, done: bool) -> None:
        card = tk.Frame(parent, bg=COLOR_CARD,
                        highlightbackground="#dddddd",
                        highlightthickness=1)
        card.pack(fill="x", pady=8, ipady=15)

        if done:
            tk.Label(card, text="✅ G-Code geladen",
                     bg=COLOR_CARD, fg=COLOR_OK,
                     font=("Segoe UI", 12, "bold")).pack(anchor="w",
                                                          padx=20, pady=(5, 5))
            tk.Label(card, text=self.app.state.file_summary_gcode(),
                     bg=COLOR_CARD, fg=COLOR_TEXT,
                     font=("Segoe UI", 10)).pack(anchor="w", padx=20)
        else:
            tk.Label(card, text="📄 SCHRITT 2: G-Code laden",
                     bg=COLOR_CARD, fg=COLOR_HEADER,
                     font=("Segoe UI", 12, "bold")).pack(anchor="w",
                                                          padx=20, pady=(5, 5))
            tk.Label(card, text="Lade das Sinumerik- oder "
                                "Heidenhain-Programm.",
                     bg=COLOR_CARD, fg=COLOR_TEXT_LIGHT,
                     font=("Segoe UI", 10)).pack(anchor="w", padx=20)

            btn_frame = tk.Frame(card, bg=COLOR_CARD)
            btn_frame.pack(fill="x", padx=20, pady=15)

            tk.Button(btn_frame, text="📁  G-Code auswählen…",
                      command=self.app.browse_gcode,
                      bg=COLOR_HEADER, fg="white", bd=0,
                      padx=20, pady=10,
                      font=("Segoe UI", 11, "bold"),
                      cursor="hand2").pack(side="left")

            tk.Label(btn_frame,
                     text="oder Datei ins Fenster ziehen",
                     bg=COLOR_CARD, fg=COLOR_TEXT_LIGHT,
                     font=("Segoe UI", 9, "italic")).pack(side="left",
                                                          padx=15)

    def _build_step_verify(self, parent) -> None:
        card = tk.Frame(parent, bg=COLOR_CARD,
                        highlightbackground="#dddddd",
                        highlightthickness=1)
        card.pack(fill="x", pady=8, ipady=15)

        tk.Label(card, text="🎯 SCHRITT 3: Verifikation",
                 bg=COLOR_CARD, fg=COLOR_HEADER,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w",
                                                      padx=20, pady=(5, 5))
        tk.Label(card, text="Prüfe, ob der G-Code die Zeichnung "
                            "innerhalb der Toleranz umsetzt.",
                 bg=COLOR_CARD, fg=COLOR_TEXT_LIGHT,
                 font=("Segoe UI", 10)).pack(anchor="w", padx=20)

        # Toleranz-Einstellung
        tol_frame = tk.Frame(card, bg=COLOR_CARD)
        tol_frame.pack(anchor="w", padx=20, pady=15)

        tk.Label(tol_frame, text="Toleranz:",
                 bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=("Segoe UI", 10)).pack(side="left")

        self.tol_var = tk.StringVar(value=f"{self.app.state.tolerance:.2f}")
        tol_entry = tk.Entry(tol_frame, textvariable=self.tol_var,
                             width=8, font=("Segoe UI", 10))
        tol_entry.pack(side="left", padx=5)

        tk.Label(tol_frame, text="mm",
                 bg=COLOR_CARD, fg=COLOR_TEXT,
                 font=("Segoe UI", 10)).pack(side="left")

        # Prüfen-Button
        tk.Button(card, text="▶  PRÜFUNG STARTEN",
                  command=self._on_start,
                  bg=COLOR_OK, fg="white", bd=0,
                  padx=40, pady=15,
                  font=("Segoe UI", 13, "bold"),
                  cursor="hand2").pack(pady=(10, 15))

    def _on_start(self) -> None:
        try:
            self.app.state.tolerance = float(
                self.tol_var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Ungültige Eingabe",
                                 "Bitte eine Zahl für die Toleranz eingeben.")
            return
        self.app.start_verification()


# --------------------------------------------------------------------------- #
# Ergebnis-Ansicht
# --------------------------------------------------------------------------- #

class ResultFrame(tk.Frame):
    """Ergebnis der Verifikation."""

    def __init__(self, master, app: CamAppV2) -> None:
        super().__init__(master, bg=COLOR_BG)
        self.app = app
        self._build()

    def _build(self) -> None:
        result = self.app.state.verify_result
        if result is None:
            tk.Label(self, text="Kein Ergebnis vorhanden.",
                     bg=COLOR_BG, font=("Segoe UI", 12)).pack(pady=50)
            return

        ok = result.total_fail == 0

        # Header
        header_color = COLOR_OK if ok else COLOR_FAIL
        header = tk.Frame(self, bg=header_color, height=100)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Button(header, text="← Zurück",
                  command=self.app._show_dashboard,
                  bg=header_color, fg="white", bd=0,
                  font=("Segoe UI", 11),
                  activebackground=header_color,
                  activeforeground="white",
                  cursor="hand2").pack(side="left", padx=20, pady=20)

        # Zentraler Status
        status_text = "ALLES IN TOLERANZ" if ok else "NICHT BESTANDEN"
        tk.Label(header, text=status_text,
                 bg=header_color, fg="white",
                 font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(header,
                 text=f"  ·  {result.total_elements} Elemente  ·  "
                      f"max. Abweichung {result.max_distance_overall:.3f} mm",
                 bg=header_color, fg="white",
                 font=("Segoe UI", 11)).pack(side="left", padx=10)

        # Inhalt in zwei Spalten
        main = tk.Frame(self, bg=COLOR_BG)
        main.pack(fill="both", expand=True, padx=20, pady=20)

        # Links: Details
        left = tk.Frame(main, bg=COLOR_CARD,
                        highlightbackground="#dddddd",
                        highlightthickness=1, width=400)
        left.pack(side="left", fill="both", padx=(0, 10))
        left.pack_propagate(False)

        # Rechts: 3D
        right = tk.Frame(main, bg=COLOR_CARD,
                         highlightbackground="#dddddd",
                         highlightthickness=1)
        right.pack(side="right", fill="both", expand=True)

        self._build_details(left, result)
        self._build_3d(right)

        # Fußzeile mit Buttons
        footer = tk.Frame(self, bg=COLOR_BG)
        footer.pack(fill="x", padx=20, pady=(0, 20))

        tk.Button(footer, text="📄 PDF-Bericht",
                  command=self._on_pdf,
                  bg=COLOR_HEADER, fg="white", bd=0,
                  padx=20, pady=10,
                  font=("Segoe UI", 11),
                  cursor="hand2").pack(side="left")

        tk.Button(footer, text="🔄 Neue Prüfung",
                  command=self.app.reset,
                  bg=COLOR_HEADER, fg="white", bd=0,
                  padx=20, pady=10,
                  font=("Segoe UI", 11),
                  cursor="hand2").pack(side="left", padx=10)

    def _build_details(self, parent, result) -> None:
        tk.Label(parent, text="Ergebnis-Details",
                 bg=COLOR_CARD, fg=COLOR_HEADER,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w",
                                                      padx=15, pady=(15, 5))

        # Scrollbarer Bereich
        canvas = tk.Canvas(parent, bg=COLOR_CARD,
                           highlightthickness=0, height=500)
        scrollbar = tk.Scrollbar(parent, orient="vertical",
                                 command=canvas.yview)
        scrollable = tk.Frame(canvas, bg=COLOR_CARD)

        scrollable.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bohrungen
        if result.hole_groups:
            tk.Label(scrollable, text="Bohrungen",
                     bg=COLOR_CARD, fg=COLOR_TEXT,
                     font=("Segoe UI", 11, "bold")).pack(anchor="w",
                                                          padx=15,
                                                          pady=(10, 5))
            for g in result.hole_groups:
                ok = g.fail_count == 0
                icon = "✅" if ok else "❌"
                color = COLOR_OK if ok else COLOR_FAIL
                row = tk.Frame(scrollable, bg=COLOR_CARD)
                row.pack(fill="x", padx=15, pady=2)
                tk.Label(row, text=icon, bg=COLOR_CARD,
                         font=("Segoe UI", 11)).pack(side="left")
                tk.Label(row, text=g.label, bg=COLOR_CARD,
                         fg=COLOR_TEXT, anchor="w").pack(side="left",
                                                          padx=8)

        # Konturen
        if result.contour_groups:
            tk.Label(scrollable, text="Konturen",
                     bg=COLOR_CARD, fg=COLOR_TEXT,
                     font=("Segoe UI", 11, "bold")).pack(anchor="w",
                                                          padx=15,
                                                          pady=(15, 5))
            for g in result.contour_groups:
                ok = g.fail_count == 0
                icon = "✅" if ok else "❌"
                row = tk.Frame(scrollable, bg=COLOR_CARD)
                row.pack(fill="x", padx=15, pady=2)
                tk.Label(row, text=icon, bg=COLOR_CARD,
                         font=("Segoe UI", 11)).pack(side="left")
                tk.Label(row, text=g.label, bg=COLOR_CARD,
                         fg=COLOR_TEXT, anchor="w").pack(side="left",
                                                          padx=8)

    def _build_3d(self, parent) -> None:
        """3D-Ansicht mit STLViewer."""
        tk.Label(parent, text="3D-Ansicht",
                 bg=COLOR_CARD, fg=COLOR_HEADER,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w",
                                                      padx=15, pady=(15, 5))

        viewer = STLViewer(parent)
        viewer.pack(fill="both", expand=True, padx=10, pady=10)

    def _on_pdf(self) -> None:
        messagebox.showinfo(
            "PDF-Bericht",
            "PDF-Bericht wird in einer späteren Version ergänzt.\n\n"
            "Für jetzt: Ergebnis über Screenshot dokumentieren.")


# --------------------------------------------------------------------------- #
# Einstiegspunkt
# --------------------------------------------------------------------------- #

def run() -> None:
    app = CamAppV2()
    app.mainloop()


if __name__ == "__main__":
    run()