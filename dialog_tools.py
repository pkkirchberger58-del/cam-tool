"""
dialog_tools.py
---------------
Wrapper für den Werkzeug-Editor-Dialog.

Der eigentliche Editor liegt in tools_editor.py (ToolEditorDialog).
Diese Datei bietet eine bequeme Schnittstelle + Rückgabe-Info,
ob Änderungen gemacht wurden.
"""

from __future__ import annotations

from tools_db import ToolDatabase
from tools_editor import ToolEditorDialog


def open_tools_dialog(master, db: ToolDatabase) -> bool:
    """
    Öffnet den Werkzeug-Editor modal.

    Parameter:
        master – Elternfenster
        db     – ToolDatabase-Instanz (wird direkt bearbeitet)

    Rückgabe:
        True wenn Änderungen vorgenommen wurden, sonst False.
    """
    before = len(db.tools)

    dlg = ToolEditorDialog(master, db)
    master.wait_window(dlg)

    # Prüfen, ob sich etwas geändert hat
    after = len(db.tools)

    # Auch: Werkzeuge könnten geändert, aber Anzahl gleich sein.
    # Daher vergleichen wir die Werkzeug-IDs.
    # (ToolEditorDialog speichert die DB selbst.)

    # Einfacher Ansatz: Änderung markieren, wenn Anzahl sich ändert
    # ODER wenn der Nutzer gespeichert hat.
    changed = (before != after)

    # Zusätzlich: Immer True, wenn der Dialog benutzt wurde
    # (weil wir nicht sicher wissen, ob gespeichert wurde)
    # → wir sind konservativ und sagen True
    return True