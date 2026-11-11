# Box Inserts — prototype

Minimal parametric box-insert generator with a FastAPI web GUI.

Exports:

- **STL** — 3D print (floor ON by default; floorless supported)
- **SVG / DXF** — laser cut of 3–6 mm wood/foam (finger-joint walls, lid latch slots, divider slots)

Geometry uses NumPy + numpy-stl + svgwrite + ezdxf (Build123d/CadQuery not required for this MVP).

## Setup

```bash
cd apps/insert-prototype
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the GUI

```bash
cd apps/insert-prototype
python3 app.py
# → http://127.0.0.1:8765
```

Or:

```bash
uvicorn app:app --host 127.0.0.1 --port 8765
```

## Sample exports (CLI)

```bash
python3 scripts/generate_samples.py
```

Writes demo STL/SVG/DXF under `../../media/prototype/` (Project store).

## Demo defaults

- Outside: **280 × 200 × 50 mm**
- Inside length and width are smaller by twice the material thickness (3 mm → inside **274 × 194 mm**)
- Thickness: 3 mm · Kerf: 0.15 mm
- Dividers: one vertical, one horizontal
