"""
test_verify.py
--------------
Test der Verifikation: DXF gegen G-Code prüfen.
"""

import sys
import os

from gcode_parser import parse_file
from dxf_loader import load_dxf
from verify import verify_dxf_against_gcode, VerifyConfig


def main():
    if len(sys.argv) < 3:
        print("Verwendung: python test_verify.py <gcode.mpf> <zeichnung.dxf>")
        sys.exit(1)

    gcode_path = sys.argv[1]
    dxf_path = sys.argv[2]

    if not os.path.isfile(gcode_path):
        print(f"Fehler: G-Code '{gcode_path}' nicht gefunden.")
        sys.exit(1)
    if not os.path.isfile(dxf_path):
        print(f"Fehler: DXF '{dxf_path}' nicht gefunden.")
        sys.exit(1)

    print("=" * 72)
    print(f"  Verifikations-Test")
    print(f"    G-Code : {gcode_path}")
    print(f"    DXF    : {dxf_path}")
    print("=" * 72)

    # Parsen
    print("\n[1/3] G-Code parsen …")
    parse_result = parse_file(gcode_path)
    print(f"      {len(parse_result.motions)} Bewegungen")

    print("[2/3] DXF laden …")
    dxf_content = load_dxf(dxf_path)
    print(f"      {len(dxf_content.contours)} Konturen, "
          f"{len(dxf_content.holes)} Bohrungen")

    print("[3/3] Verifikation …")
    config = VerifyConfig(tolerance=0.01)
    result = verify_dxf_against_gcode(dxf_content, parse_result, config)

    # Zusammenfassung
    print("\n" + "-" * 72)
    print("  Gesamtergebnis")
    print("-" * 72)
    print(result.summary())

    # Details pro Kontur
    print("\n" + "-" * 72)
    print("  Ergebnis pro Kontur")
    print("-" * 72)
    for c in result.contour_checks:
        status = "✓ OK" if c.tolerance_ok else "✗ FEHLER"
        kind = {"outer": "Außen", "inner": "Innen", "hole": "Bohrung"}\
            .get(c.kind, c.kind)
        print(f"\n  [{c.contour_index:>2}] {kind:>8}  "
              f"Layer='{c.layer}'  {status}")
        print(f"      Punkte: {c.points_checked}  "
              f"OK: {c.points_ok}  "
              f"FAIL: {c.points_fail}")
        print(f"      Max. Abweichung: {c.max_distance:.4f} mm  "
              f"Mittel: {c.mean_distance:.4f} mm")

        if not c.tolerance_ok:
            # Erste 5 fehlerhafte Punkte ausgeben
            fails = [p for p in c.point_checks if not p.ok][:5]
            print(f"      Erste fehlerhafte Punkte:")
            for p in fails:
                print(f"        ({p.point[0]:>8.3f}, {p.point[1]:>8.3f})  "
                      f"→ nächster G-Code-Punkt: "
                      f"({p.closest_gcode_point[0]:>8.3f}, "
                      f"{p.closest_gcode_point[1]:>8.3f})  "
                      f"Abstand: {p.distance:.4f} mm")

    # Fazit
    print("\n" + "=" * 72)
    failing = result.failing_contours()
    if not failing:
        print(f"  ✓✓✓ BESTANDEN – alle Konturen innerhalb "
              f"±{result.tolerance} mm")
    else:
        print(f"  ✗✗✗ DURCHGEFALLEN – {len(failing)} von "
              f"{len(result.contour_checks)} Konturen über Toleranz")
    print("=" * 72)


if __name__ == "__main__":
    main()