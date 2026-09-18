"""
test_path_builder.py
--------------------
Test der Kontur-Berechnung an einer echten G-Code-Datei.
"""

import sys
import os

from gcode_parser import parse_file
from path_builder import build_paths, BuildConfig


# Werkzeugdurchmesser
TOOL_DIAMETERS = {
    10: 20.0,
    14: 5.0,
    1:  8.0,
}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "test.mpf"
    if not os.path.isfile(path):
        print(f"Fehler: Datei '{path}' nicht gefunden.")
        sys.exit(1)

    print("=" * 72)
    print(f"  Path-Builder-Test: {path}")
    print("=" * 72)

    print("\n[1/2] Parsing …")
    parse_result = parse_file(path)
    print(f"      {len(parse_result.motions)} Bewegungen, "
          f"{len(parse_result.tool_changes)} Werkzeuge")

    print("[2/2] Kontur-Berechnung …")
    config = BuildConfig(
        z_tolerance=0.01,
        spatial_tolerance=0.05,
        arc_resolution=0.1,
        min_contour_length=1.0,
        min_points=4,
        apply_cutter_comp=True,
        contour_match_tolerance=0.1,
    )
    result = build_paths(parse_result, config, TOOL_DIAMETERS)

    # Zusammenfassung
    print("\n" + "-" * 72)
    print("  Zusammenfassung")
    print("-" * 72)
    print(result.summary())

    # Konturen pro Werkzeug
    print("\n" + "-" * 72)
    print("  Konturen pro Werkzeug")
    print("-" * 72)
    for tool, contours in sorted(result.by_tool.items()):
        print(f"\n  Werkzeug T{tool} (Ø{TOOL_DIAMETERS.get(tool, '?')}):")
        for i, c in enumerate(contours, 1):
            x0, y0, x1, y1 = c.bbox()
            closed = "geschlossen" if c.closed else "offen"
            print(f"    [{i:>3}] {len(c.points):>5} Punkte  "
                  f"Z={c.z:>8.3f}  {closed:>12}  {c.cutter_comp.value}  "
                  f"Länge={c.length:>9.2f}  "
                  f"BBox=({x0:>7.2f},{y0:>7.2f}) → "
                  f"({x1:>7.2f},{y1:>7.2f})")

    # Bohrungen
    print("\n" + "-" * 72)
    print(f"  Bohrungen ({len(result.holes)})")
    print("-" * 72)
    for i, h in enumerate(result.holes, 1):
        print(f"    [{i:>2}] X={h.x:>8.3f}  Y={h.y:>8.3f}  "
              f"Ø{h.diameter:.2f}  T{h.tool}  "
              f"Tiefe={h.depth:.2f} mm  (Zeile {h.source_line})")

    if result.warnings:
        print("\n" + "-" * 72)
        print(f"  Warnungen: {len(result.warnings)}")
        for w in result.warnings[:10]:
            print(f"    ⚠ {w}")

    print("\n" + "=" * 72)
    print("  ✓ Path-Builder abgeschlossen.")
    print("=" * 72)


if __name__ == "__main__":
    main()