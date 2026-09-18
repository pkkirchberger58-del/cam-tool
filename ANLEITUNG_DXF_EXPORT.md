# Anleitung: DXF-Export für das CAM-Verifikations-Tool

**Zweck:** Diese Anleitung beschreibt, wie Sie eine DXF-Datei erstellen,
die unser CAM-Verifikations-Tool zuverlässig einlesen kann.

**Zielgruppe:** Konstrukteure, NC-Programmierer, CAD-Anwender

**Wichtig:** Falsch exportierte DXFs (z. B. 3D-Modelle) können vom Tool
nicht gelesen werden. Diese Anleitung zeigt, wie man es richtig macht.

---

## 📋 Inhalt

1. [Grundregel](#grundregel)
2. [AutoCAD-Export (Hauptweg)](#autocad)
3. [Inventor-Export (Sonderfall)](#inventor)
4. [Was NICHT exportieren](#was-nicht)
5. [Checkliste vor dem Versenden](#checkliste)
6. [Selbsttest mit `check_dxf.py`](#selbsttest)
7. [Häufige Fehler und Lösungen](#fehler)

---

## 1. Grundregel

> **Immer 2D-DXF, niemals 3D-Modell.**

Unser Tool liest **2D-Konturen** (Linien, Bögen, Kreise). Ein **3D-Modell**
(wie es z. B. beim direkten Export aus Inventor entsteht) kann nicht
verarbeitet werden.

**Prüfmerkmal in der DXF:**

| Zeichen | Bedeutung |
|---|---|
| ✅ `LINE`, `ARC`, `CIRCLE`, `LWPOLYLINE` | 2D-Geometrie, OK |
| ❌ `3DFACE`, `MESH`, `BODY` | 3D-Modell, NICHT OK |
| ⚠️ `SPLINE` | Kann OK sein (echte Kurven) – aber prüfen |
| ⚠️ `MTEXT`, `DIMENSION`, `HATCH` | Anmerkungen, werden ignoriert |

**Faustregel:** Eine **2D-Zeichnung** für die Fertigung exportieren, nicht
das **3D-Modell**.

---

## 2. AutoCAD-Export (Hauptweg)

### 2.1 Zeichnung vorbereiten

1. **2D-Zeichnung** in AutoCAD öffnen
2. **Nicht benötigte Elemente entfernen** oder in eigene Layer legen:
   - Bemaßungen
   - Texte und Beschriftungen
   - Mittellinien / Achsen
   - Schraffuren (HATCH)
   - Symbole (Oberflächen, Toleranzen, Schweißnähte)
3. **Konturen prüfen:**
   - Alle Konturen geschlossen (Außenkontur, Taschen)
   - Bohrungen als **Kreis** (nicht als Polylinie mit Bögen)
   - Rundungen als **Bogen** (ARC)

**Tipp:** Sie können die Zeichnung kopieren und nur die reinen Konturen
in der Kopie lassen. Original bleibt unverändert.

### 2.2 Layer-Namen (empfohlen)

Damit die Konturen später eindeutig zugeordnet werden können:

| Layer | Inhalt |
|---|---|
| `KONTUR` oder `OUTLINE` | Außenkontur |
| `TASCHE` oder `POCKET` | Taschen, Nuten |
| `BOHRUNG` oder `HOLE` | Bohrungen |
| `HILFSLINIEN` | wird gelöscht |

Layer-Namen sind **nicht zwingend** – aber hilfreich.

### 2.3 Export als DXF

1. **Datei → Speichern unter…**
2. **Dateityp:** `AutoCAD 2018 DXF (*.dxf)`
   - Oder `AutoCAD 2013 DXF` für maximale Kompatibilität
   - **Nicht** `AutoCAD 2024 DXF` (neuere Versionen sind oft inkompatibel)
3. **Dateiname:** sprechend, z. B. `Teil-4711_Kontur.dxf`
4. **Speichern**

**Alternativ** (bei Bedarf):
