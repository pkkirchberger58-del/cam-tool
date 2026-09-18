"""
check_dxf.py
------------
Selbsttest für Konstrukteure: Prüft, ob eine DXF-Datei für das
CAM-Verifikations-Tool verwendbar ist.

Aufruf:
    python check_dxf.py meine_zeichnung.dxf

Ausgabe:
    - Entity-Typen (LINE, ARC, CIRCLE, ...)
    - 3DFACE-Prüfung (falls 3D-Modell erkannt wird → Warnung)
    - Konturen und Kreise
    - Bereich (Bounding-Box)
    - Ergebnis: OK / NICHT VERWENDBAR / WARNUNG
"""

from __future__ import annotations

import math
import os
import sys
from collections import Counter

try:
    import ezdxf
except ImportError:
    print("FEHLER: ezdxf nicht installiert.")
    print("Bitte ausführen: pip install ezdxf")
    sys.exit(1)

try:
    from dxf_loader import load_dxf
except ImportError:
    print("FEHLER: dxf_loader.py nicht gefunden.")
    print("Stelle sicher, dass check_dxf.py im cam_tool-Ordner liegt.")
    sys.exit(1)


# --------------------------------------------------------------------------- #
# Ausgabe-Helfer
# --------------------------------------------------------------------------- #

def _line(char: str = "─", width: int = 72) -> str:
    return char * width


def _header(text: str) -> str:
    return f"\n{_line()}\n  {text}\n{_line()}\n"


# --------------------------------------------------------------------------- #
# Hauptprüfung
# --------------------------------------------------------------------------- #

def check_dxf(path: str) -> int:
    """
    Prüft eine DXF-Datei und gibt einen Statuscode zurück:
        0 = OK (grün)
        1 = Warnung (gelb)
        2 = Nicht verwendbar (rot)
    """
    if not os.path.isfile(path):
        print(f"FEHLER: Datei nicht gefunden: {path}")
        return 2

    # Größe
    size_kb = os.path.getsize(path) / 1024

    print()
    print("=" * 72)
    print(f"  DXF-Check: {os.path.basename(path)}")
    print("=" * 72)
    print()
    print(f"  Dateigröße:  {size_kb:>10.1f} KB")
    print(f"  Pfad:        {os.path.abspath(path)}")

    # ---------------------------------------------------------------------- #
    # 1. Direkt mit ezdxf einlesen (Entity-Details)
    # ---------------------------------------------------------------------- #

    try:
        doc = ezdxf.readfile(path)
    except Exception as exc:
        print()
        print(f"FEHLER beim Öffnen: {type(exc).__name__}: {exc}")
        return 2

    msp = doc.modelspace()

    # DXF-Version und Einheiten
    dxf_version = doc.dxfversion
    ins_units = doc.header.get("$INSUNITS", None)
    unit_map = {1: "inch", 2: "feet", 4: "mm", 5: "cm", 6: "m"}
    units = unit_map.get(ins_units, f"unbekannt (Code {ins_units})")

    print(f"  DXF-Version: {dxf_version}")
    print(f"  Einheiten:   {units}")

    # ---------------------------------------------------------------------- #
    # 2. Entity-Typen zählen
    # ---------------------------------------------------------------------- #

    types = Counter(e.dxftype() for e in msp)

    print(_header("Entities im Modellbereich"))

    if not types:
        print("  (KEINE Entities gefunden!)")
        print()
        print("  → Die Zeichnung ist leer oder alle Entities sind in Blöcken.")
        print("  → Bitte prüfen, ob im Modellbereich wirklich Geometrie liegt.")
        return 2

    # Sortierte Ausgabe
    relevant = ["LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE",
                "SPLINE", "ELLIPSE", "3DFACE", "SOLID", "INSERT",
                "MTEXT", "TEXT", "DIMENSION", "HATCH", "LEADER"]

    for etype in relevant:
        if etype in types:
            marker = ""
            if etype == "3DFACE":
                marker = "  ← PROBLEM (3D-Modell)"
            elif etype in ("MTEXT", "TEXT", "DIMENSION", "HATCH", "LEADER"):
                marker = "  ← Anmerkung, wird ignoriert"
            print(f"  {etype:<15}: {types[etype]:>5}{marker}")

    # Andere Entities
    for etype, count in types.items():
        if etype not in relevant:
            print(f"  {etype:<15}: {count:>5}")

    # ---------------------------------------------------------------------- #
    # 3. Kritische Prüfung: 3D-BREP?
    # ---------------------------------------------------------------------- #

    print(_header("Prüfung"))

    issues = []
    warnings = []

    # 3D-BREP-Erkennung
    n_3dface = types.get("3DFACE", 0)
    if n_3dface > 0:
        issues.append(
            f"{n_3dface} × 3DFACE gefunden → das ist ein 3D-Modell, "
            "keine 2D-Zeichnung!")

    # INSERT im Modellbereich → könnte 3D-Block sein
    n_insert = types.get("INSERT", 0)
    if n_insert > 0 and n_3dface == 0:
        warnings.append(
            f"{n_insert} × INSERT gefunden → Zeichnung enthält Blöcke. "
            "Wird geprüft.")

    # Nur Anmerkungen?
    nur_anmerkungen = all(
        t in ("TEXT", "MTEXT", "DIMENSION", "HATCH", "LEADER")
        for t in types.keys())
    if nur_anmerkungen:
        issues.append("Nur Anmerkungen (Texte, Bemaßungen) gefunden – "
                      "keine Konturen!")

    # Wenig Geometrie?
    n_geometrie = (types.get("LINE", 0)
                   + types.get("ARC", 0)
                   + types.get("CIRCLE", 0)
                   + types.get("LWPOLYLINE", 0)
                   + types.get("POLYLINE", 0)
                   + types.get("SPLINE", 0)
                   + types.get("ELLIPSE", 0))

    if n_geometrie == 0:
        issues.append("Keine 2D-Geometrie (LINE/ARC/CIRCLE) gefunden!")

    # ---------------------------------------------------------------------- #
    # 4. Über unseren dxf_loader laden
    # ---------------------------------------------------------------------- #

    print()
    try:
        content = load_dxf(path)
        n_contours = len(content.contours)
        n_holes = len(content.holes)
        print(f"  Vom CAM-Loader erkannt:")
        print(f"    Konturen: {n_contours}")
        print(f"    Kreise:   {n_holes}")
    except Exception as exc:
        print(f"  FEHLER im CAM-Loader: {type(exc).__name__}: {exc}")
        issues.append(f"Loader-Fehler: {exc}")
        n_contours = 0
        n_holes = 0

    # ---------------------------------------------------------------------- #
    # 5. Bereich berechnen
    # ---------------------------------------------------------------------- #

    print(_header("Bereich (Bounding-Box)"))

    try:
        xs, ys = [], []
        for c in content.contours:
            xs.extend(c.points[:, 0].tolist())
            ys.extend(c.points[:, 1].tolist())
        for h in content.holes:
            xs.append(h.x)
            ys.append(h.y)

        if xs and ys:
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)
            width = xmax - xmin
            height = ymax - ymin

            print(f"  X: {xmin:>10.2f}  bis  {xmax:>10.2f}  "
                  f"(Breite: {width:>8.2f})")
            print(f"  Y: {ymin:>10.2f}  bis  {ymax:>10.2f}  "
                  f"(Höhe:   {height:>8.2f})")
            print()
            print(f"  Werkstück-Nullpunkt:")
            print(f"    (0, 0) liegt im Bereich: "
                  f"{'JA' if xmin <= 0 <= xmax and ymin <= 0 <= ymax else 'NEIN'}")

            # Nullpunkt-Warnung
            if not (xmin <= 0 <= xmax and ymin <= 0 <= ymax):
                warnings.append(
                    "Der Punkt (0,0) liegt NICHT im Werkstückbereich. "
                    "Prüfe den Nullpunkt!")
        else:
            print("  (keine Geometrie – kein Bereich berechenbar)")
    except Exception as exc:
        print(f"  Fehler bei Bereichsberechnung: {exc}")

    # ---------------------------------------------------------------------- #
    # 6. Ergebnis
    # ---------------------------------------------------------------------- #

    print(_header("Ergebnis"))

    if issues:
        print("  ❌ NICHT VERWENDBAR")
        print()
        for iss in issues:
            print(f"     • {iss}")
        print()
        print("  Bitte die Zeichnung als 2D-DXF exportieren und erneut prüfen.")
        return 2

    if warnings:
        print("  ⚠️  WARNUNG")
        print()
        for w in warnings:
            print(f"     • {w}")
        print()
        print("  Die DXF ist möglicherweise verwendbar, aber bitte prüfen.")
        return 1

    # Prüfung bestanden
    print("  ✅ OK FÜR CAM-TOOL")
    print()
    print(f"     {n_contours} Konturen und {n_holes} Kreise erkannt.")
    print(f"     Alle Entities sind 2D-Geometrie.")
    return 0


# --------------------------------------------------------------------------- #
# Einstiegspunkt
# --------------------------------------------------------------------------- #

def main():
    if len(sys.argv) < 2:
        print()
        print("Verwendung: python check_dxf.py <datei.dxf>")
        print()
        print("Prüft eine DXF-Datei auf Verwendbarkeit im CAM-Tool.")
        print()
        sys.exit(1)

    path = sys.argv[1]
    status = check_dxf(path)

    print()
    print("=" * 72)
    if status == 0:
        print("  Status: ✅  OK")
    elif status == 1:
        print("  Status: ⚠️   WARNUNG – bitte prüfen")
    else:
        print("  Status: ❌  NICHT VERWENDBAR")
    print("=" * 72)
    print()

    sys.exit(status)


if __name__ == "__main__":
    main()