# Sinumerik CAM-Tool & STL 3D-Visualisierung

Tkinter-Anwendung zur Visualisierung von STL-Modellen mit Platz für
CAM-Parameter und G-Code-Vorschau.

## Features

- 3D-STL-Viewer mit Zoom, Pan, Rotate (Matplotlib-NavigationToolbar)
- Asynchrones Laden großer Dateien (GUI bleibt reaktionsfähig)
- Proportionale Darstellung (kein Verzerren der Achsen)
- Facettenanzahl und Bounding-Box werden angezeigt
- Skalierbares PanedWindow-Layout
- Statuszeile mit Feedback

## Installation

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Start

```bash
python main.py
```

## Projektstruktur

```
cam_tool/
├── main.py            Einstiegspunkt
├── gui.py             Hauptfenster
├── viewer3d.py        Wiederverwendbarer STL-Viewer
├── requirements.txt
└── README.md
```

## Hinweis

Das Paket heißt **numpy-stl** (Import: `from stl import mesh`).
Installiere NICHT `stl`, das ist ein anderes Paket und inkompatibel.