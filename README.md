# LaserBox

A box designer for laser cutting and 3D printing. Set the size, walls, dividers, and lid, then download an STL, SVG, or DXF.

## Run

Needs Python 3.12.

```powershell
cd apps/insert-prototype
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8765

On macOS or Linux, activate the venv with `source .venv/bin/activate`.

## Use

Length and width can be inside or outside dimensions. The demo box is 280 × 200 × 50 mm, 3 mm thick, with a 0.15 mm kerf. Add dividers in the form or drag them on the plan. Lids: cap, sit on top, tab and slot, latch, or a closed top. Save or load the design as JSON.

## License

[AGPL-3.0](LICENSE)

## How it was programmed

Written in [Cursor](https://cursor.com) with its AI coding agent, primarily Grok 4.7. The geometry and export server are Python (FastAPI, NumPy, numpy-stl, svgwrite, ezdxf). The interface is HTML, CSS, and JavaScript.
