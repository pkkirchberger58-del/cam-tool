"""
test_parser.py
--------------
Test des erweiterten G-Code-Parsers.
Liest test.mpf aus dem aktuellen Verzeichnis und gibt eine
umfassende Zusammenfassung aus.
"""

import os
import sys
from gcode_parser import parse_file, MotionType


def main():
    # Datei aus Argument oder Standardname
    path = sys.argv[1] if len(sys.argv) > 1 else "test.mpf"

    if not os.path.isfile(path):
        print(f"Fehler: Datei '{path}' nicht gefunden.")
        sys.exit(1)

    print("=" * 72)
    print(f"  Parser-Test: {path}")
    print("=" * 72)

    result = parse_file(path)

    print(f"\nProgrammnummer      : {result.program_number or '(nicht erkannt)'}")
    print(f"Bewegungen          : {len(result.motions)}")
    print(f"  davon schneidend  : {len(result.cutting_motions)}")
    print(f"  davon Eilgang     : {sum(1 for m in result.motions if m.motion_type == MotionType.RAPID)}")
    print(f"  davon Helix       : {sum(1 for m in result.motions if m.is_helix)}")
    print(f"  davon Kreisbögen  : {sum(1 for m in result.motions if m.motion_type in (MotionType.ARC_CW, MotionType.ARC_CCW))}")

    print(f"\nWerkzeugwechsel      : {result.tool_changes}")
    print(f"Erkannte Zyklen     : {result.cycles or 'keine'}")
    print(f"Z-Bereich           : {result.min_z:.3f} … {result.max_z:.3f} mm")

    # Werkzeug-genaue Z-Analyse
    if result.tool_changes:
        print("\nZ-Bereich pro Werkzeug:")
        for t in result.tool_changes:
            zs = [m.end[2] for m in result.motions if m.tool == t]
            if zs:
                print(f"  T{t:>2}  : {min(zs):8.3f} … {max(zs):8.3f} mm   "
                      f"({len(zs)} Bewegungen)")

    # Warnungen und Fehler
    print(f"\nWarnungen           : {len(result.warnings)}")
    for w in result.warnings[:20]:
        print(f"  ⚠ {w}")
    if len(result.warnings) > 20:
        print(f"  … und {len(result.warnings) - 20} weitere")

    print(f"\nFehler              : {len(result.errors)}")
    for e in result.errors[:10]:
        print(f"  ✗ {e}")

    # Beispiel-Bewegungen aus jeder Kategorie
    print("\n" + "-" * 72)
    print("  Beispiel-Bewegungen (erste 3 je Kategorie):")
    print("-" * 72)

    for label, pred in [
        ("Eilgang",   lambda m: m.motion_type == MotionType.RAPID),
        ("Linear",    lambda m: m.motion_type == MotionType.LINEAR),
        ("Bogen XY",  lambda m: m.motion_type in (MotionType.ARC_CW, MotionType.ARC_CCW) and not m.is_helix),
        ("Helix",     lambda m: m.is_helix),
    ]:
        samples = [m for m in result.motions if pred(m)][:3]
        if not samples:
            continue
        print(f"\n  {label}:")
        for m in samples:
            print(f"    Z{m.line_no:>4}  {m.motion_type.value:>3}  "
                  f"({m.start[0]:8.3f},{m.start[1]:8.3f},{m.start[2]:7.3f}) → "
                  f"({m.end[0]:8.3f},{m.end[1]:8.3f},{m.end[2]:7.3f})  "
                  f"T{m.tool or '-':>2}  {m.plane.value}  "
                  f"{'HELIX' if m.is_helix else '     '}")

    print("\n" + "=" * 72)
    if not result.errors:
        print("  ✓ Parsing ohne Fehler abgeschlossen.")
    else:
        print(f"  ⚠ Parsing mit {len(result.errors)} Fehler(n) abgeschlossen.")
    print("=" * 72)


if __name__ == "__main__":
    main()