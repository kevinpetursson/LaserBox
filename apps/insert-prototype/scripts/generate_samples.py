#!/usr/bin/env python3
"""Generate sample STL / SVG / DXF exports into the Project media folder."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from insert_gen.laser import export_dxf, export_svg
from insert_gen.mesh import export_stl
from insert_gen.model import InsertParams, demo_params

# Project store media path (apps → store root → media/prototype)
MEDIA = ROOT.parents[1] / "media" / "prototype"


def main() -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    base = demo_params()

    with_floor = base.model_copy(update={"floor": True})
    floorless = base.model_copy(update={"floor": False})

    paths = [
        export_stl(with_floor, MEDIA / "demo-insert-floor.stl"),
        export_stl(floorless, MEDIA / "demo-insert-floorless.stl"),
        export_svg(with_floor, MEDIA / "demo-insert-laser.svg"),
        export_dxf(with_floor, MEDIA / "demo-insert-laser.dxf"),
    ]
    for p in paths:
        size = p.stat().st_size
        print(f"wrote {p} ({size} bytes)")


if __name__ == "__main__":
    main()
