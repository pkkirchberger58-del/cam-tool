"""
tools_editor.py
---------------
Dialog zum Bearbeiten der Werkzeugdatenbank.
Enthält eine Tabelle (Treeview) mit Add/Edit/Delete/Save.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from tools_db import Tool, ToolDatabase, TOOL_TYPES, TOOL_TYPE_LABELS, \
                     MATERIALS, COATINGS


class ToolEditorDialog(tk.Toplevel):
    """Modaler Dialog zum Bearbeiten der Werkzeugliste."""

    COLUMNS = [
        ("id",         "ID",        70,  "w"),
        ("name",       "Name",      200, "w"),
        ("type",       "Typ",       120, "w"),
        ("diameter",   "Ø (mm)",    70,  "e"),
        ("corner",     "Eckenradius", 80, "e"),
        ("flutes",     "Zähne",     50,  "e"),
        ("rpm_range",  "Drehzahl",  110, "w"),
        ("feed_range", "Vorschub",  110, "w"),
        ("material",   "Material",  80,  "w"),
        ("coating",    "Beschichtung", 110, "w"),
    ]

    def __init__(self, master, db: ToolDatabase) -> None:
        super().__init__(master)
        self.title("Werkzeug-Datenbank")
        self.geometry("1100x600")
        self.transient(master)
        self.grab_set()

        self.db = db
        self._changed = False

        self._build_ui()
        self._refresh_table()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=6)
        toolbar.pack(side="top", fill="x")

        ttk.Button(toolbar, text="➕ Neu",
                   command=self._on_add).pack(side="left", padx=2)
        ttk.Button(toolbar, text="✏ Bearbeiten",
                   command=self._on_edit).pack(side="left", padx=2)
        ttk.Button(toolbar, text="🗑 Löschen",
                   command=self._on_delete).pack(side="left", padx=2)
        ttk.Button(toolbar, text="💾 Speichern",
                   command=self._on_save).pack(side="left", padx=2)
        ttk.Button(toolbar, text="↺ Neu laden",
                   command=self._on_reload).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Schließen",
                   command=self.destroy).pack(side="right", padx=2)

        # Tabelle
        wrapper = ttk.Frame(self, padding=(6, 0, 6, 6))
        wrapper.pack(fill="both", expand=True)

        cols = [c[0] for c in self.COLUMNS]
        self.tree = ttk.Treeview(wrapper, columns=cols, show="headings",
                                 selectmode="browse")
        for cid, label, width, anchor in self.COLUMNS:
            self.tree.heading(cid, text=label)
            self.tree.column(cid, width=width, anchor=anchor, stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)

        ysb = ttk.Scrollbar(wrapper, orient="vertical", command=self.tree.yview)
        ysb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=ysb.set)

        self.tree.bind("<Double-1>", lambda e: self._on_edit())

        # Statuszeile
        self._status = tk.StringVar(value=f"{len(self.db.tools)} Werkzeuge")
        ttk.Label(self, textvariable=self._status, anchor="w",
                  padding=(8, 4)).pack(side="bottom", fill="x")

    # --------------------------------------------------------------- Tabelle --
    def _refresh_table(self) -> None:
        # Alte Zeilen entfernen
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for t in self.db.tools:
            self.tree.insert("", "end", iid=t.id, values=(
                t.id, t.name, TOOL_TYPE_LABELS.get(t.type, t.type),
                f"{t.diameter:.2f}", f"{t.corner_radius:.2f}",
                t.flutes,
                f"{t.rpm_min}-{t.rpm_max}",
                f"{t.feed_min}-{t.feed_max}",
                t.material, t.coating,
            ))
        self._status.set(f"{len(self.db.tools)} Werkzeuge"
                         + (" (ungespeicherte Änderungen)"
                            if self._changed else ""))

    # -------------------------------------------------------------- Aktionen --
    def _on_add(self) -> None:
        new_id = self.db.next_free_id()
        blank = Tool(id=new_id, name="Neues Werkzeug")
        dlg = ToolEditDialog(self, blank, is_new=True)
        self.wait_window(dlg)
        if dlg.result is not None:
            try:
                self.db.add(dlg.result)
                self._changed = True
                self._refresh_table()
                self.tree.selection_set(dlg.result.id)
            except ValueError as exc:
                messagebox.showerror("Fehler", str(exc), parent=self)

    def _on_edit(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Keine Auswahl",
                                "Bitte ein Werkzeug auswählen.", parent=self)
            return
        tool_id = sel[0]
        tool = self.db.get(tool_id)
        if tool is None:
            return

        dlg = ToolEditDialog(self, tool, is_new=False)
        self.wait_window(dlg)
        if dlg.result is not None:
            try:
                self.db.replace(tool_id, dlg.result)
                self._changed = True
                self._refresh_table()
                self.tree.selection_set(dlg.result.id)
            except ValueError as exc:
                messagebox.showerror("Fehler", str(exc), parent=self)

    def _on_delete(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        tool = self.db.get(sel[0])
        if tool is None:
            return
        if not messagebox.askyesno(
            "Löschen bestätigen",
            f"Werkzeug '{tool.id} – {tool.name}' wirklich löschen?",
            parent=self):
            return
        self.db.remove(tool.id)
        self._changed = True
        self._refresh_table()

    def _on_save(self) -> None:
        self.db.save()
        self._changed = False
        self._refresh_table()
        self._status.set(f"Gespeichert in {self.db.path}")

    def _on_reload(self) -> None:
        if self._changed and not messagebox.askyesno(
            "Neu laden",
            "Ungespeicherte Änderungen verwerfen?", parent=self):
            return
        self.db.load()
        self._changed = False
        self._refresh_table()


# --------------------------------------------------------------------------- #

class ToolEditDialog(tk.Toplevel):
    """Bearbeitet ein einzelnes Werkzeug."""

    def __init__(self, master, tool: Tool, is_new: bool) -> None:
        super().__init__(master)
        self.title("Werkzeug hinzufügen" if is_new else f"Werkzeug {tool.id} bearbeiten")
        self.geometry("500x620")
        self.transient(master)
        self.grab_set()

        self._orig = tool
        self._is_new = is_new
        self.result: Optional[Tool] = None

        self._build_ui(tool)

    def _build_ui(self, tool: Tool) -> None:
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        self.vars: dict[str, tk.Variable] = {}

        def add_row(r, key, label, widget="entry",
                    values=None, width=None):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
            if widget == "entry":
                var = tk.StringVar(value=str(getattr(tool, key)))
                ttk.Entry(frm, textvariable=var, width=width or 20)\
                    .grid(row=r, column=1, sticky="ew", pady=3)
            elif widget == "combo":
                var = tk.StringVar(value=str(getattr(tool, key)))
                ttk.Combobox(frm, textvariable=var, values=values,
                             state="readonly", width=width or 20)\
                    .grid(row=r, column=1, sticky="ew", pady=3)
            else:
                raise ValueError(widget)
            self.vars[key] = var

        # Felder
        add_row(0,  "id",            "ID:")
        add_row(1,  "name",          "Name:")
        add_row(2,  "type",          "Typ:", widget="combo",
                values=[TOOL_TYPE_LABELS[t] for t in TOOL_TYPES])
        add_row(3,  "diameter",      "Durchmesser (mm):")
        add_row(4,  "corner_radius", "Eckenradius (mm):")
        add_row(5,  "flute_length",  "Schneidenlänge (mm):")
        add_row(6,  "total_length",  "Gesamtlänge (mm):")
        add_row(7,  "flutes",        "Zähnezahl:")
        add_row(8,  "material",      "Material:", widget="combo",
                values=MATERIALS)
        add_row(9,  "coating",       "Beschichtung:", widget="combo",
                values=COATINGS)
        add_row(10, "rpm_min",       "Drehzahl min (U/min):")
        add_row(11, "rpm_max",       "Drehzahl max (U/min):")
        add_row(12, "feed_min",      "Vorschub min (mm/min):")
        add_row(13, "feed_max",      "Vorschub max (mm/min):")
        add_row(14, "tip_angle",     "Spitzenwinkel (°):")
        add_row(15, "thread_pitch",  "Gewindesteigung (mm):")
        add_row(16, "comment",       "Kommentar:")

        # Anfangswerte: Combobox für Typ auf Label umstellen
        type_key = tool.type if tool.type in TOOL_TYPES else "fraeser"
        self.vars["type"].set(TOOL_TYPE_LABELS[type_key])

        # Buttons
        btns = ttk.Frame(self, padding=(12, 6, 12, 12))
        btns.pack(side="bottom", fill="x")
        ttk.Button(btns, text="OK", command=self._on_ok)\
            .pack(side="right", padx=2)
        ttk.Button(btns, text="Abbrechen", command=self.destroy)\
            .pack(side="right", padx=2)

        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def _on_ok(self) -> None:
        # Combobox-Label zurück auf internen Typ umstellen
        type_label = self.vars["type"].get()
        type_value = next(
            (k for k, v in TOOL_TYPE_LABELS.items() if v == type_label),
            "fraeser")
        self.vars["type"].set(type_value)

        # Alle Werte einsammeln
        data = {k: v.get() for k, v in self.vars.items()}
        data["type"] = type_value

        # Zahlen konvertieren
        try:
            numeric = ["diameter", "corner_radius", "flute_length",
                       "total_length", "tip_angle", "thread_pitch"]
            for k in numeric:
                data[k] = float(str(data[k]).replace(",", "."))
            for k in ["flutes", "rpm_min", "rpm_max", "feed_min", "feed_max"]:
                data[k] = int(str(data[k]))
        except ValueError as exc:
            messagebox.showerror("Ungültiger Wert",
                                 f"Bitte Zahlen prüfen: {exc}", parent=self)
            return

        new_tool = Tool.from_dict(data)
        errors = new_tool.validate()
        if errors:
            messagebox.showerror("Ungültiges Werkzeug",
                                 "\n".join(errors), parent=self)
            return

        self.result = new_tool
        self.destroy()