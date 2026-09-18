"""
test_compare.py
---------------
Test der Verifikation: DXF vs. G-Code.
"""

import os
import sys

from gcode_parser import parse_file
from dxf_loader import load_dxf
from compare import verify, CompareConfig


def main():
    if len(sys.argv) < 3:
        print("Verwendung: python test_compare.py <gcode.mpf> <zeichnung.dxf>")
        sys.exit(1)

    gcode_path = sys.argv[1]
    dxf_path = sys.argv[2]

    for p in (gcode_path, dxf_path):
        if not os.path.isfile(p):
            print(f"Fehler: '{p}' nicht gefunden.")
            sys.exit(1)

    print("=" * 78)
    print(f"  VERIFIKATION")
    print(f"    G-Code : {gcode_path}")
    print(f"    DXF    : {dxf_path}")
    print("=" * 78)

    # 1) Parsen
    print("\n[1/3] G-Code parsen …")
    parse_result = parse_file(gcode_path)
    print(f"      {len(parse_result.motions)} Bewegungen")

    # 2) DXF laden
    print("[2/3] DXF laden …")
    dxf = load_dxf(dxf_path)
    print(f"      {len(dxf.contours)} Konturen, {len(dxf.holes)} Kreise")

    # 3) Verifikation
    print("[3/3] Verifikation läuft …\n")
    config = CompareConfig(
        tolerance=0.01,
        arc_resolution=0.05,
        hole_min_diameter=1.0,
        hole_max_diameter=200.0,
    )
    result = verify(dxf, parse_result, config)

    # ---- Gesamtergebnis ----
    print("\n" + "=" * 78)
    print("  GESAMTERGEBNIS")
    print("=" * 78)
    print(result.summary())

    # ---- Bohrungen: nach Gruppe ----
    print("\n" + "-" * 78)
    print(f"  BOHRUNGEN ({len(result.hole_results)} geprüft)")
    print("-" * 78)
    for g in result.hole_groups:
        status = "OK" if g.fail_count == 0 else "FEHLER"
        print(f"\n  [{status}] {g.label}")
        print(f"      {g.ok_count}/{g.total} OK, "
              f"{g.fail_count} FEHLER, "
              f"max. Abw. {g.worst_distance:.4f} mm")
        for e in g.elements:
            if not e.ok:
                print(f"        [X] {e.label}: "
                      f"{e.points_fail}/{e.points_checked} Punkte fehlerhaft, "
                      f"max {e.max_distance:.4f} mm")

    # ---- Konturen ----
    print("\n" + "-" * 78)
    print(f"  KONTUREN ({len(result.contour_results)} geprüft)")
    print("-" * 78)
    for g in result.contour_groups:
        status = "OK" if g.fail_count == 0 else "FEHLER"
        print(f"\n  [{status}] {g.label}")
        print(f"      {g.ok_count}/{g.total} OK, "
              f"{g.fail_count} FEHLER, "
              f"max. Abw. {g.worst_distance:.4f} mm")

        # Die 5 schlechtesten anzeigen
        sorted_e = sorted(g.elements, key=lambda e: -e.max_distance)
        for e in sorted_e[:5]:
            status_e = "[OK]" if e.ok else "[X] "
            label = e.label[:60] if e.label else ""
            print(f"        {status_e} {label:<60} "
                  f"{e.points_checked:>5} Punkte, "
                  f"max {e.max_distance:.4f} mm")

    # ---- Gesamturteil ----
    print("\n" + "=" * 78)
    if result.total_fail == 0:
        print(f"  BESTANDEN - alle {result.total_elements} Elemente OK")
    else:
        print(f"  DURCHGEFALLEN - {result.total_fail} von "
              f"{result.total_elements} Elementen mit Abweichungen "
              f"ueber ±{result.tolerance} mm")
    print("=" * 78)


if __name__ == "__main__":
    main()