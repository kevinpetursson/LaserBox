"""A one-sheet finger-joint kerf test.

Five 50 mm corners. Each pair is compensated with a different kerf, using the
same edge offset as the box. The pair that fits is the kerf to enter. NOW is
drawn on the pair for the kerf currently typed in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ezdxf
import svgwrite

from .laser import Poly, Vec2, _finger_edge, _offset_kerf, _translate
from .model import InsertParams, odd_finger_count

CORNER_HEIGHT = 50.0
CORNER_DEPTH = 13.5
KERF_STEP = 0.05
KERF_COUNT = 5
PIECE_GAP = 5.0
PAIR_GAP = 12.0
SHEET_W = 540.0

# Strokes on a 4 by 6 grid, y upward. A closed loop repeats its first point.
_GLYPHS: dict[str, list[list[tuple[float, float]]]] = {
    "0": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1)]],
    "1": [[(1, 0), (3, 0)], [(2, 0), (2, 6)], [(1, 4.6), (2, 6)]],
    "2": [[(0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (0, 0), (4, 0)]],
    "3": [
        [(0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3), (1, 3)],
        [(1, 3), (3, 3), (4, 2), (4, 1), (3, 0), (1, 0), (0, 1)],
    ],
    "4": [[(3.2, 0), (3.2, 6), (0, 2.3), (4, 2.3)]],
    "5": [[(4, 6), (0, 6), (0, 3.2), (3, 3.2), (4, 2.2), (4, 1), (3, 0), (0, 0)]],
    "6": [[(3.6, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 2.5), (3, 3.2), (0, 3.2)]],
    "7": [[(0, 6), (4, 6), (1, 0)], [(1.3, 3), (3.5, 3)]],
    "8": [
        [(1, 3), (0, 4.1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 4.1), (3, 3), (1, 3)],
        [(3, 3), (4, 1.9), (4, 1), (3, 0), (1, 0), (0, 1), (0, 1.9), (1, 3)],
    ],
    "9": [[(0.4, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 3.5), (1, 2.8), (4, 2.8)]],
    ".": [[(1.4, 0.15), (2.6, 0.15), (2.6, 1.35), (1.4, 1.35), (1.4, 0.15)]],
    "N": [[(0, 0), (0, 6), (4, 0), (4, 6)]],
    "O": [[(0, 1), (1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1)]],
    "W": [[(0, 6), (1, 0), (2, 3.3), (3, 0), (4, 6)]],
}


@dataclass
class KerfPiece:
    outline: Poly
    marks: list[Poly]
    origin: Vec2
    kerf: float
    side: str
    caption: str


def format_kerf(value: float) -> str:
    """Two decimals, or three when the value is not a hundredth of a millimetre."""
    cents = round(value * 100.0)
    if abs(value * 100.0 - cents) < 1e-4:
        return f"{value:.2f}"
    return f"{value:.3f}"


def kerf_samples(current: float, step: float = KERF_STEP, count: int = KERF_COUNT) -> list[float]:
    """`count` kerfs, `step` apart, with the typed kerf kept in the set."""
    current = round(max(0.0, current), 4)
    half = count // 2
    start = current - half * step
    if start < 0:
        start = 0.0
    samples = [round(start + index * step, 4) for index in range(count)]
    nearest = min(range(count), key=lambda index: abs(samples[index] - current))
    samples[nearest] = current
    unique: list[float] = []
    for value in samples:
        if all(abs(value - kept) > 1e-6 for kept in unique):
            unique.append(value)
    while len(unique) < count:
        unique.append(round(max(unique) + step, 4))
    unique.sort()
    return unique


def _corner_outline(depth: float, height: float, thickness: float, fingers: int, male: bool, side: str) -> Poly:
    """A rectangular offcut. Fingers are on `side` and stick out past the rectangle."""
    raw = _finger_edge(height, thickness, fingers, male, 0.0)
    if side == "left":
        joint = [(y, x) for x, y in raw]
        outline = list(joint)
        outline.append((depth, height))
        outline.append((depth, 0.0))
        outline.append(joint[0])
        return outline
    joint = [(depth - y, x) for x, y in raw]
    outline = [(0.0, 0.0), joint[0]]
    outline.extend(joint[1:])
    outline.append((0.0, height))
    outline.append((0.0, 0.0))
    return outline


def _text_width(text: str, size: float) -> float:
    if not text:
        return 0.0
    scale = size / 6.0
    return len(text) * 4.0 * scale + (len(text) - 1) * scale


def _rotated_strokes(text: str, cx: float, bottom: float, size: float) -> list[Poly]:
    """Text running upward. The top of each letter points left."""
    scale = size / 6.0
    step = 5.0 * scale
    strokes: list[Poly] = []
    y = bottom
    for char in text:
        for stroke in _GLYPHS[char]:
            strokes.append([(cx + (3.0 - py) * scale, y + px * scale) for px, py in stroke])
        y += step
    return strokes


def _label_size(groups: list[list[str]], depth: float, height: float) -> float:
    """One size for the sheet. The cap height has to fit the narrow piece."""
    size = min(8.0, depth - 3.0)
    while size > 2.4:
        gap = size * 0.5
        too_long = False
        for lines in groups:
            length = sum(_text_width(line, size) for line in lines) + gap * (len(lines) - 1)
            if length > height - 4.0:
                too_long = True
                break
        if not too_long:
            return size
        size = round(size - 0.2, 2)
    return 2.4


def _caption_marks(lines: list[str], cx: float, cy: float, size: float) -> list[Poly]:
    """Stack the lines along the piece. NOW sits above the number."""
    gap = size * 0.5
    total = sum(_text_width(line, size) for line in lines) + gap * (len(lines) - 1)
    y = cy - total / 2.0
    marks: list[Poly] = []
    for line in lines:
        marks.extend(_rotated_strokes(line, cx, y, size))
        y += _text_width(line, size) + gap
    return marks


def _shift(poly: Poly, dx: float, dy: float) -> Poly:
    return [(x - dx, y - dy) for x, y in poly]


def build_kerf_test(params: InsertParams) -> list[KerfPiece]:
    """Nested corner pairs. Female fingers face left, male fingers face right."""
    current = round(max(0.0, params.kerf), 4)
    fingers = odd_finger_count(CORNER_HEIGHT, params.finger_length)
    thickness = params.thickness
    pieces: list[KerfPiece] = []
    cursor_x = 0.0
    cursor_y = 0.0
    row_h = 0.0
    samples = kerf_samples(current)
    groups: list[list[str]] = []
    for sample in samples:
        lines = [format_kerf(sample)]
        if abs(sample - current) < 1e-6:
            lines.append("NOW")
        groups.append(lines)
    size = _label_size(groups, CORNER_DEPTH, CORNER_HEIGHT)

    for sample, lines in zip(samples, groups):
        caption = " ".join(lines)
        built: list[tuple[Poly, list[Poly], str]] = []
        for side, male in (("left", False), ("right", True)):
            nominal = _corner_outline(
                CORNER_DEPTH, CORNER_HEIGHT, thickness, fingers, male, side
            )
            outline = _offset_kerf(nominal, sample, outward=True)
            min_x = min(point[0] for point in outline)
            min_y = min(point[1] for point in outline)
            outline = _shift(outline, min_x, min_y)
            marks = _caption_marks(
                lines,
                CORNER_DEPTH / 2.0 - min_x,
                CORNER_HEIGHT / 2.0 - min_y,
                size,
            )
            built.append((outline, marks, "female" if side == "left" else "male"))
        pair_w = sum(max(point[0] for point in outline) for outline, _, _ in built) + PIECE_GAP
        if cursor_x > 0 and cursor_x + pair_w > SHEET_W:
            cursor_x = 0.0
            cursor_y += row_h + PAIR_GAP
            row_h = 0.0
        for outline, marks, side in built:
            width = max(point[0] for point in outline)
            height = max(point[1] for point in outline)
            pieces.append(
                KerfPiece(
                    outline=outline,
                    marks=marks,
                    origin=(cursor_x, cursor_y),
                    kerf=sample,
                    side=side,
                    caption=caption,
                )
            )
            cursor_x += width + PIECE_GAP
            row_h = max(row_h, height)
        cursor_x += PAIR_GAP - PIECE_GAP
    return pieces


def _upright_for_svg(marks: list[Poly]) -> list[Poly]:
    """Turn Y-up label strokes upright for an SVG viewer.

    Cut paths stay in the same Y-up coordinates as the box files. An SVG viewer
    draws Y downward, so those strokes would read upside down. DXF keeps the
    Y-up strokes, which read upright in a DXF viewer.
    """
    ys = [y for stroke in marks for _x, y in stroke]
    if not ys:
        return marks
    mid = (min(ys) + max(ys)) / 2.0
    return [[(x, 2.0 * mid - y) for x, y in stroke] for stroke in marks]


def _bounds(pieces: list[KerfPiece]) -> tuple[float, float]:
    max_x = 10.0
    max_y = 10.0
    for piece in pieces:
        paths = [piece.outline, *piece.marks]
        for path in paths:
            for x, y in path:
                max_x = max(max_x, piece.origin[0] + x)
                max_y = max(max_y, piece.origin[1] + y)
    return max_x + 8.0, max_y + 8.0


def export_kerf_svg(params: InsertParams, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pieces = build_kerf_test(params)
    width, height = _bounds(pieces)
    drawing = svgwrite.Drawing(
        str(path),
        size=(f"{width:.2f}mm", f"{height:.2f}mm"),
        viewBox=f"0 0 {width:.2f} {height:.2f}",
    )
    cuts = drawing.g(id="cut", fill="none", stroke="#000000", stroke_width=0.1)
    labels = drawing.g(id="label", fill="none", stroke="#1d4e89", stroke_width=0.15)
    for piece in pieces:
        outline = _translate(piece.outline, piece.origin)
        cuts.add(drawing.polygon(points=[(f"{x:.4f}", f"{y:.4f}") for x, y in outline]))
        for stroke in _upright_for_svg(piece.marks):
            placed = _translate(stroke, piece.origin)
            labels.add(drawing.polyline(points=[(f"{x:.4f}", f"{y:.4f}") for x, y in placed]))
    drawing.add(cuts)
    drawing.add(labels)
    drawing.save()
    return path


def export_kerf_dxf(params: InsertParams, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pieces = build_kerf_test(params)
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    doc.layers.add("CUT", color=1)
    doc.layers.add("LABEL", color=5)
    space = doc.modelspace()
    for piece in pieces:
        outline = _translate(piece.outline, piece.origin)
        if outline[0] != outline[-1]:
            outline = outline + [outline[0]]
        space.add_lwpolyline(outline, close=True, dxfattribs={"layer": "CUT"})
        for stroke in piece.marks:
            placed = _translate(stroke, piece.origin)
            space.add_lwpolyline(placed, close=False, dxfattribs={"layer": "LABEL"})
    doc.saveas(str(path))
    return path
