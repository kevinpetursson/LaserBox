"""FastAPI web GUI for the box-insert prototype."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from insert_gen.laser import build_panels, export_dxf, export_svg, panel_label
from insert_gen.mesh import build_print_parts, export_stl
from insert_gen.model import InsertParams, demo_params

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

app = FastAPI(title="Box Inserts Prototype", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/api/defaults")
def defaults() -> dict:
    return demo_params().model_dump()


def _num(value: float) -> float:
    return float(value)


def _poly(points) -> list:
    return [[_num(x), _num(y)] for x, y in points]


@app.post("/api/preview")
def preview(params: InsertParams) -> dict:
    """Assembled triangles for the 3D view and nested panels for the 2D drawing."""
    panels = []
    for panel in build_panels(params):
        text, _font, anchor = panel_label(panel)
        panels.append(
            {
                "name": panel.name,
                "label": text,
                "label_at": [_num(anchor[0]), _num(anchor[1])],
                "origin": [_num(panel.origin[0]), _num(panel.origin[1])],
                "outline": _poly(panel.outline),
                "holes": [_poly(hole) for hole in panel.holes],
            }
        )
    triangles = []
    parts = []
    for name, tris in build_print_parts(params):
        parts.append({"name": name, "start": len(triangles), "count": len(tris)})
        for tri in tris:
            triangles.append([[_num(c) for c in vertex] for vertex in tri])
    return {
        "outer_length": params.outer_length,
        "outer_width": params.outer_width,
        "inner_length": params.inner_length,
        "inner_width": params.inner_width,
        "thickness": params.thickness,
        "height": params.height,
        "floor": params.floor,
        "panels": panels,
        "triangles": triangles,
        "parts": parts,
    }


ExportFmt = Literal["stl", "svg", "dxf"]


@app.post("/api/export/{fmt}")
def export(fmt: ExportFmt, params: InsertParams) -> Response:
    if fmt not in ("stl", "svg", "dxf"):
        raise HTTPException(400, f"Unknown format: {fmt}")
    suffix = f".{fmt}"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        out = Path(tmp.name)
    try:
        if fmt == "stl":
            export_stl(params, out)
            media = "model/stl"
            filename = "insert.stl"
        elif fmt == "svg":
            export_svg(params, out)
            media = "image/svg+xml"
            filename = "insert.svg"
        else:
            export_dxf(params, out)
            media = "application/dxf"
            filename = "insert.dxf"
        data = out.read_bytes()
    finally:
        out.unlink(missing_ok=True)
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def main() -> None:
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
