"""
test_preprocess.py
------------------
Test der DXF-Vorverarbeitung.

Zeigt:
- Anzahl erkannter Kreise
- Anzahl gebildeter Ketten
- Verworfene Symbole
- Hierarchie der Konturen (Verschachtelung)
- Klassifikation (outer / inner / pocket / circle / open)
"""

import os
import sys
import math

from dxf_loader import load_dxf
from dxf_preprocessor import preprocess_dxf, PreprocessConfig


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "test.dxf"

    if not os.path.isfile(path):
        print(f"Fehler: Datei '{path}' nicht gefunden.")
        sys.exit(1)

    print("=" * 76)
    print(f"  Preprocessing-Test: {path}")
    print("=" * 76)

    # ---- 1) DXF laden ----
    print("\n[1/2] DXF laden …")
    dxf = load_dxf(path)
    print(f"      {len(dxf.contours)} rohe Konturen, "
          f"{len(dxf.holes)} explizite Bohrungen")
    print(f"      Layer: {dxf.layers or '(keine)'}")
    print(f"      Einheit: {dxf.units}")

    # ---- 2) Vorverarbeitung ----
    print("\n[2/2] Vorverarbeitung …")
    config = PreprocessConfig(
        chain_tolerance=0.05,
        close_tolerance=0.1,
        symbol_fraction=0.005,      # 0,5 % der größten Kontur
        min_absolute_length=0.3,
        circle_fit_tolerance=0.02,
        min_circle_points=16,
    )
    result = preprocess_dxf(dxf, config)

    # ---- 3) Zusammenfassung ----
    print("\n" + "-" * 76)
    print("  Zusammenfassung")
    print("-" * 76)
    print(result.summary())

    # ---- 4) Konturen nach Typ gruppiert ----
    print("\n" + "-" * 76)
    print("  Konturen nach Typ")
    print("-" * 76)

    by_kind: dict[str, list] = {}
    for c in result.contours:
        by_kind.setdefault(c.kind, []).append(c)

    for kind in ["outer", "inner", "pocket", "circle", "open", "?"]:
        if kind not in by_kind:
            continue
        lst = by_kind[kind]
        print(f"\n  {kind.upper()} ({len(lst)} Konturen):")
        # Sortieren nach Diagonale (größte zuerst)
        for c in sorted(lst, key=lambda x: -x.diag)[:20]:
            x0, y0, x1, y1 = c.bbox()
            circle_info = ""
            if c.radius:
                circle_info = (f"  Ø{c.radius * 2:.2f} "
                               f"@ ({c.center[0]:.2f}, {c.center[1]:.2f})")
            print(f"    N={len(c.points):>4}  "
                  f"Länge={c.length:>9.2f}  "
                  f"depth={c.depth}  "
                  f"{'closed' if c.closed else 'open  '}  "
                  f"BBox=({x0:>8.2f},{y0:>8.2f})→"
                  f"({x1:>8.2f},{y1:>8.2f})"
                  f"{circle_info}")
        if len(lst) > 20:
            print(f"    … und {len(lst) - 20} weitere")

    # ---- 5) Kreis-Zusammenfassung ----
    circles = by_kind.get("circle", [])
    if circles:
        print("\n" + "-" * 76)
        print("  Kreise – gruppiert nach Durchmesser")
        print("-" * 76)
        diameter_groups: dict[float, list] = {}
        for c in circles:
            d = round(c.radius * 2, 1)
            diameter_groups.setdefault(d, []).append(c)

        for d in sorted(diameter_groups.keys()):
            lst = diameter_groups[d]
            print(f"  Ø{d:>6.1f} mm  →  {len(lst)} Stück")
            for c in lst[:3]:
                print(f"      @ ({c.center[0]:>8.2f}, {c.center[1]:>8.2f})")
            if len(lst) > 3:
                print(f"      … und {len(lst) - 3} weitere")

    # ---- 6) Hierarchie-Übersicht ----
    print("\n" + "-" * 76)
    print("  Hierarchie (Verschachtelung)")
    print("-" * 76)
    depth_counts: dict[int, int] = {}
    for c in result.contours:
        if not c.closed:
            continue
        depth_counts[c.depth] = depth_counts.get(c.depth, 0) + 1

    for d in sorted(depth_counts.keys()):
        label = {0: "äußerste Konturen",
                 1: "in einer anderen liegend",
                 2: "doppelt verschachtelt"}.get(d, f"Tiefe {d}")
        print(f"  depth={d}: {depth_counts[d]:>3}  ({label})")

    # ---- 7) Gesamtstatistik ----
    print("\n" + "-" * 76)
    print("  Statistik")
    print("-" * 76)
    for k, v in result.stats.items():
        print(f"  {k:<25}: {v}")

    # ---- 8) Ergebnis ----
    print("\n" + "=" * 76)
    n_contours = len(result.contours)
    n_circles = len(by_kind.get("circle", []))
    n_closed = sum(1 for c in result.contours if c.closed)
    print(f"  ✓ {n_contours} Konturen extrahiert")
    print(f"    davon {n_circles} Kreise (Bohrungen / Rundungen)")
    print(f"    davon {n_closed} geschlossen")
    print(f"    davon {n_contours - n_closed} offen")
    print("=" * 76)


if __name__ == "__main__":
    main()