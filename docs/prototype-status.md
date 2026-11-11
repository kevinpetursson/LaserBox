# Box Inserts prototype — status

Minimal Python parametric insert generator with a FastAPI web GUI. **Runnable MVP** for dual export (print + laser).

## How to run locally

```bash
cd /cursor/stores/self/apps/insert-prototype   # or your checked-out Project store path
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Open **http://127.0.0.1:8765**

Edit box size, clearance, thickness (3–6 mm), kerf, floor on/off, lid slots, and the divider list (including angled segments). Download STL, SVG, or DXF from the Export buttons.

CLI sample generation:

```bash
python3 scripts/generate_samples.py
```

## What’s implemented

| Feature | Status |
| --- | --- |
| Outer rectangle sized to box interior (demo **280×200×50 mm** ID) | Yes |
| Fit clearance from walls | Yes (default 0.5 mm → 279×199 mm insert) |
| Material thickness 3–6 mm | Yes (default 3) |
| Laser kerf param | Yes (applied to panel outlines) |
| Editable dividers (straight + angled) | Yes |
| Laser: finger joints on wall ends | Yes |
| Laser: latching-lid slots in walls | Yes |
| Laser: floor divider slots | Yes |
| Print STL with floor (default) | Yes |
| Print STL floorless | Yes |
| SVG + DXF export | Yes |
| Simple web GUI (plan preview canvas) | Yes |

Stack: **Python + FastAPI + NumPy + numpy-stl + svgwrite + ezdxf** (pragmatic fallback; Build123d/CadQuery not required).

## Example exports

Generated under `media/prototype/`:

- `demo-insert-floor.stl` — print solid with floor
- `demo-insert-floorless.stl` — walls + dividers only
- `demo-insert-laser.svg` — nested cut panels
- `demo-insert-laser.dxf` — same cut paths

## Known limits

- Print mesh is a **union of overlapping boxes** (not a watertight BREP boolean). Fine for FDM preview; not ideal for manifold-critical slicers.
- Finger joints are a simple odd-count pattern; mating left/right male/female pairing is basic — tune kerf on your laser before trusting fit.
- Divider↔wall T-slots and floor seating are approximate (no full tab/mortise assembly animation).
- Laser nest is a single-sheet left-to-right layout (≈600 mm wrap), not a true packer.
- No lid panel geometry yet — only **slots** in walls for a latching lid.
- No Build123d/CadQuery path in this MVP (can be swapped in later for true solids).

## App path

`apps/insert-prototype/`
