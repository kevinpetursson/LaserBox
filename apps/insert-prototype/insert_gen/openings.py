"""Opening shapes, SVG outlines, and the checks that keep a cut on the piece."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from .model import Opening

Vec2 = Tuple[float, float]
Poly = List[Vec2]

_MIN_SIZE = 2.0
_ARC_STEPS = 8


@dataclass
class OpeningReport:
    """Frames and per-opening notes collected while the panels are built."""

    frames: List[dict] = field(default_factory=list)
    notes: List[dict] = field(default_factory=list)
    users: dict = field(default_factory=dict)

    def frame(
        self,
        host: str,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        margin: float,
        outline: Sequence[Vec2] | None = None,
        cuts: Sequence[Sequence[Vec2]] | None = None,
    ) -> None:
        self.frames.append(
            {
                "host": host,
                "x0": round(x0, 3),
                "y0": round(y0, 3),
                "x1": round(x1, 3),
                "y1": round(y1, 3),
                "margin": round(margin, 3),
                "outline": [[round(x, 2), round(y, 2)] for x, y in (outline or [])],
                "cuts": [
                    [[round(x, 2), round(y, 2)] for x, y in poly]
                    for poly in (cuts or [])
                    if len(poly) >= 3
                ],
            }
        )

    def note(self, host: str, item: dict) -> None:
        polygon = [[round(x, 3), round(y, 3)] for x, y in item.get("polygon") or []]
        self.notes.append(
            {
                "host": host,
                "index": item["index"],
                "ok": bool(item["ok"]),
                "reason": item["reason"],
                "polygon": polygon,
            }
        )
        if item.get("polygon") and (item["ok"] or item.get("cut")):
            self.users.setdefault(host, []).append(list(item["polygon"]))


def _rotate(points: Sequence[Vec2], degrees: float) -> Poly:
    if abs(degrees) < 1e-9:
        return list(points)
    angle = math.radians(degrees)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return [(x * cos_a - y * sin_a, x * sin_a + y * cos_a) for x, y in points]


def _arc(cx: float, cy: float, radius: float, a0: float, a1: float, steps: int) -> Poly:
    count = max(1, steps)
    return [
        (
            cx + radius * math.cos(a0 + (a1 - a0) * i / count),
            cy + radius * math.sin(a0 + (a1 - a0) * i / count),
        )
        for i in range(count + 1)
    ]


def _dedupe(points: Sequence[Vec2]) -> Poly:
    out: Poly = []
    for point in points:
        if not out or abs(point[0] - out[-1][0]) > 1e-6 or abs(point[1] - out[-1][1]) > 1e-6:
            out.append(point)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-6 and abs(out[0][1] - out[-1][1]) < 1e-6:
        out.pop()
    return out


def _local_shape(shape: str, width: float, height: float, radius: float) -> Poly:
    """Finished outline centered on the origin, counter-clockwise, Y up."""
    w = width / 2.0
    h = height / 2.0
    if shape == "oval":
        steps = 40
        return [
            (w * math.cos(2.0 * math.pi * i / steps), h * math.sin(2.0 * math.pi * i / steps))
            for i in range(steps)
        ]
    if shape == "obround":
        if width >= height:
            radius = h
            cx = w - radius
            pts: Poly = []
            pts.extend(_arc(cx, 0.0, radius, -math.pi / 2.0, math.pi / 2.0, 12))
            pts.extend(_arc(-cx, 0.0, radius, math.pi / 2.0, 3.0 * math.pi / 2.0, 12))
            return _dedupe(pts)
        radius = w
        cy = h - radius
        pts = []
        pts.extend(_arc(0.0, -cy, radius, math.pi, 2.0 * math.pi, 12))
        pts.extend(_arc(0.0, cy, radius, 0.0, math.pi, 12))
        return _dedupe(pts)
    if shape == "roundrect":
        limit = min(w, h)
        radius = min(max(0.0, radius), limit)
        if radius < 0.05:
            return [(-w, -h), (w, -h), (w, h), (-w, h)]
        pts = []
        pts.extend(_arc(w - radius, -h + radius, radius, -math.pi / 2.0, 0.0, _ARC_STEPS)[:-1])
        pts.extend(_arc(w - radius, h - radius, radius, 0.0, math.pi / 2.0, _ARC_STEPS)[:-1])
        pts.extend(_arc(-w + radius, h - radius, radius, math.pi / 2.0, math.pi, _ARC_STEPS)[:-1])
        pts.extend(_arc(-w + radius, -h + radius, radius, math.pi, 3.0 * math.pi / 2.0, _ARC_STEPS)[:-1])
        return _dedupe(pts)
    return [(-w, -h), (w, -h), (w, h), (-w, h)]


def _scale_svg(opening: Opening) -> Poly | None:
    if len(opening.points) < 3:
        return None
    xs = [p[0] for p in opening.points]
    ys = [p[1] for p in opening.points]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    native_w = max(xs) - min(xs)
    native_h = max(ys) - min(ys)
    if native_w < 1e-6 or native_h < 1e-6:
        return None
    sx = opening.width / native_w
    sy = opening.height / native_h
    return [((x - cx) * sx, (y - cy) * sy) for x, y in opening.points]


def finished_polygon(opening: Opening) -> Poly | None:
    """The opening at its finished size, in piece coordinates."""
    if opening.shape == "svg":
        local = _scale_svg(opening)
        if local is None:
            return None
    else:
        if opening.width < _MIN_SIZE or opening.height < _MIN_SIZE:
            return None
        local = _local_shape(opening.shape, opening.width, opening.height, opening.radius)
    placed = _rotate(local, opening.rotation)
    return [(x + opening.x, y + opening.y) for x, y in placed]


def cut_polygon(opening: Opening, kerf: float) -> Poly | None:
    """The laser path. It is the finished outline inset by half the kerf."""
    shrink = max(0.0, kerf)
    if opening.shape == "svg":
        finished = finished_polygon(opening)
        if finished is None:
            return None
        if shrink <= 1e-9:
            return finished
        return _inset_polygon(finished, shrink / 2.0)
    width = opening.width - shrink
    height = opening.height - shrink
    if width < 0.4 or height < 0.4:
        return None
    radius = max(0.0, opening.radius - shrink / 2.0)
    local = _local_shape(opening.shape, width, height, radius)
    placed = _rotate(local, opening.rotation)
    return [(x + opening.x, y + opening.y) for x, y in placed]


def _shoelace(poly: Sequence[Vec2]) -> float:
    area = 0.0
    count = len(poly)
    for i in range(count):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % count]
        area += x0 * y1 - x1 * y0
    return area / 2.0


def _ensure_ccw(poly: Sequence[Vec2]) -> Poly:
    pts = list(poly)
    if _shoelace(pts) < 0.0:
        pts.reverse()
    return pts


def _inset_polygon(poly: Sequence[Vec2], dist: float) -> Poly | None:
    """Move every edge inward. A spike or a crossing means the kerf ate the shape."""
    pts = _dedupe(_ensure_ccw(poly))
    count = len(pts)
    if count < 3 or dist <= 0:
        return pts or None
    lines: List[Tuple[float, float, float, float]] = []
    for i in range(count):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % count]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1e-8:
            return None
        nx, ny = -dy / length, dx / length
        lines.append((dx, dy, x0 + nx * dist, y0 + ny * dist))
    out: Poly = []
    for i in range(count):
        ax, ay, px, py = lines[(i - 1) % count]
        bx, by, qx, qy = lines[i]
        cross = ax * by - ay * bx
        if abs(cross) < 1e-10:
            return None
        t = ((qx - px) * by - (qy - py) * bx) / cross
        hit = (px + ax * t, py + ay * t)
        vx, vy = pts[i]
        if math.hypot(hit[0] - vx, hit[1] - vy) > dist * 4.0 + 1.0:
            return None
        out.append(hit)
    if len(_dedupe(out)) < 3 or abs(_shoelace(out)) < 0.2 or _self_intersects(out):
        return None
    return out


def _self_intersects(poly: Sequence[Vec2]) -> bool:
    count = len(poly)
    for i in range(count):
        a, b = poly[i], poly[(i + 1) % count]
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue
            c, d = poly[j], poly[(j + 1) % count]
            if _segments_cross(a, b, c, d):
                return True
    return False


def _segments_cross(a: Vec2, b: Vec2, c: Vec2, d: Vec2) -> bool:
    def cross(p: Vec2, q: Vec2, r: Vec2) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1 = cross(a, b, c)
    d2 = cross(a, b, d)
    d3 = cross(c, d, a)
    d4 = cross(c, d, b)
    if abs(d1) < 1e-8 or abs(d2) < 1e-8 or abs(d3) < 1e-8 or abs(d4) < 1e-8:
        return False
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def _point_in_poly(x: float, y: float, poly: Sequence[Vec2]) -> bool:
    inside = False
    count = len(poly)
    for i in range(count):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % count]
        if (y0 > y) != (y1 > y):
            x_cross = (x1 - x0) * (y - y0) / (y1 - y0) + x0
            if x < x_cross:
                inside = not inside
    return inside


def _bbox(poly: Sequence[Vec2]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _polys_hit(a: Sequence[Vec2], b: Sequence[Vec2]) -> bool:
    ax0, ay0, ax1, ay1 = _bbox(a)
    bx0, by0, bx1, by1 = _bbox(b)
    if ax1 < bx0 - 1e-6 or bx1 < ax0 - 1e-6 or ay1 < by0 - 1e-6 or by1 < ay0 - 1e-6:
        return False
    if any(_point_in_poly(x, y, b) for x, y in a):
        return True
    if any(_point_in_poly(x, y, a) for x, y in b):
        return True
    count_a = len(a)
    count_b = len(b)
    for i in range(count_a):
        p, q = a[i], a[(i + 1) % count_a]
        for j in range(count_b):
            if _segments_cross(p, q, b[j], b[(j + 1) % count_b]):
                return True
    return False


def _inside_rect(poly: Sequence[Vec2], bounds: Tuple[float, float, float, float], margin: float) -> bool:
    x0, y0, x1, y1 = bounds
    left, bottom, right, top = x0 + margin, y0 + margin, x1 - margin, y1 - margin
    if right - left < _MIN_SIZE or top - bottom < _MIN_SIZE:
        return False
    return all(left - 1e-6 <= x <= right + 1e-6 and bottom - 1e-6 <= y <= top + 1e-6 for x, y in poly)


def resolve_openings(
    openings: Sequence[Opening],
    bounds: Tuple[float, float, float, float],
    margin: float,
    obstacles: Sequence[Sequence[Vec2]],
    kerf: float,
) -> List[dict]:
    """Decide which openings are cut. Polygons are in piece coordinates.

    `bounds` is the flat piece, including fingers. `margin` keeps that much
    wood inside every edge. `obstacles` are joints and slots already on the piece.
    """
    accepted: List[Poly] = []
    results: List[dict] = []
    for index, opening in enumerate(openings):
        polygon = finished_polygon(opening)
        reason = _refuse_reason(opening, polygon, bounds, margin, obstacles, accepted)
        forced = bool(opening.force) and reason in _PLACEMENT
        cut = cut_polygon(opening, kerf) if reason is None or forced else None
        if (reason is None or forced) and cut is None:
            reason = "Kerf compensation removes this opening. Make it larger."
            forced = False
        ok = reason is None
        if (ok or forced) and polygon is not None:
            accepted.append(polygon)
        results.append(
            {
                "index": index,
                "ok": ok,
                "reason": "" if ok else reason,
                "polygon": polygon or [],
                "cut": cut if ok or forced else None,
            }
        )
    return results


_PLACEMENT = (
    "Leave at least the material thickness of wood around this opening.",
    "This opening overlaps another opening on this piece.",
    "This opening runs into a joint or another cut.",
)


def _refuse_reason(
    opening: Opening,
    polygon: Poly | None,
    bounds: Tuple[float, float, float, float],
    margin: float,
    obstacles: Sequence[Sequence[Vec2]],
    accepted: Sequence[Poly],
) -> str | None:
    if opening.shape == "svg" and len(opening.points) < 3:
        return "Upload an SVG for this opening."
    if opening.width < _MIN_SIZE - 1e-6 or opening.height < _MIN_SIZE - 1e-6:
        return "Width and height need to be at least 2 mm."
    if polygon is None or len(polygon) < 3:
        return "This opening has no outline."
    if _self_intersects(polygon):
        return "This outline crosses itself."
    if not _inside_rect(polygon, bounds, margin):
        return "Leave at least the material thickness of wood around this opening."
    if any(_polys_hit(polygon, other) for other in accepted):
        return "This opening overlaps another opening on this piece."
    if any(hole and _polys_hit(polygon, hole) for hole in obstacles):
        return "This opening runs into a joint or another cut."
    return None


def missing_piece_note(host: str, index: int, reason: str) -> dict:
    return {"host": host, "index": index, "ok": False, "reason": reason, "polygon": []}


# --- SVG upload -----------------------------------------------------------------

_LENGTH = re.compile(
    r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(mm|cm|in|pt|px|%)?$",
    re.IGNORECASE,
)
_TRANSFORM = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_COMMAND = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")


def _svg_length(text: str | None, fallback: float | None = None) -> float | None:
    if text is None:
        return fallback
    match = _LENGTH.match(text.strip())
    if not match or match.group(2) == "%":
        return fallback
    value = float(match.group(1))
    unit = (match.group(2) or "").lower()
    scale = {"": 1.0, "mm": 1.0, "px": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72.0}
    return value * scale.get(unit, 1.0)


def _multiply(a: Tuple[float, ...], b: Tuple[float, ...]) -> Tuple[float, float, float, float, float, float]:
    ax, bx, cx, dx, ex, fx = a
    ay, by, cy, dy, ey, fy = b
    return (
        ax * ay + cx * by,
        bx * ay + dx * by,
        ax * cy + cx * dy,
        bx * cy + dx * dy,
        ax * ey + cx * fy + ex,
        bx * ey + dx * fy + fx,
    )


def _apply(matrix: Tuple[float, ...], x: float, y: float) -> Vec2:
    return (matrix[0] * x + matrix[2] * y + matrix[4], matrix[1] * x + matrix[3] * y + matrix[5])


def _parse_transform(text: str | None) -> Tuple[float, float, float, float, float, float]:
    ident = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if not text:
        return ident
    result = ident
    for name, body in _TRANSFORM.findall(text):
        nums = [float(n) for n in _NUMBER.findall(body)]
        kind = name.lower()
        if kind == "matrix" and len(nums) == 6:
            local = tuple(nums)
        elif kind == "translate":
            tx = nums[0] if nums else 0.0
            ty = nums[1] if len(nums) > 1 else 0.0
            local = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif kind == "scale":
            sx = nums[0] if nums else 1.0
            sy = nums[1] if len(nums) > 1 else sx
            local = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif kind == "rotate":
            deg = nums[0] if nums else 0.0
            angle = math.radians(deg)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            rot = (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0)
            if len(nums) >= 3:
                cx, cy = nums[1], nums[2]
                local = _multiply(_multiply((1, 0, 0, 1, cx, cy), rot), (1, 0, 0, 1, -cx, -cy))
            else:
                local = rot
        elif kind == "skewx" and nums:
            local = (1.0, 0.0, math.tan(math.radians(nums[0])), 1.0, 0.0, 0.0)
        elif kind == "skewy" and nums:
            local = (1.0, math.tan(math.radians(nums[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        result = _multiply(result, local)
    return result


def _flatten_arc(
    x0: float,
    y0: float,
    rx: float,
    ry: float,
    phi_deg: float,
    large: bool,
    sweep: bool,
    x1: float,
    y1: float,
    chord: float,
) -> Poly:
    """Points from the current point up to the arc end, excluding the start."""
    if rx < 1e-9 or ry < 1e-9 or (abs(x1 - x0) < 1e-9 and abs(y1 - y0) < 1e-9):
        return [(x1, y1)]
    phi = math.radians(phi_deg)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x1) / 2.0, (y0 - y1) / 2.0
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale
    sign = -1.0 if large == sweep else 1.0
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = sign * math.sqrt(max(0.0, num / den)) if den > 1e-12 else 0.0
    cxp = coef * rx * y1p / ry
    cyp = coef * -ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x0 + x1) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y0 + y1) / 2.0

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        det = ux * vy - uy * vx
        return math.atan2(det, dot)

    theta = angle(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if sweep and delta < 0:
        delta += 2.0 * math.pi
    elif not sweep and delta > 0:
        delta -= 2.0 * math.pi
    span = max(abs(rx), abs(ry)) * abs(delta)
    steps = max(2, min(80, int(math.ceil(span / max(chord, 0.2)))))
    pts: Poly = []
    for i in range(1, steps + 1):
        ang = theta + delta * i / steps
        x = cx + rx * math.cos(ang) * cos_p - ry * math.sin(ang) * sin_p
        y = cy + rx * math.cos(ang) * sin_p + ry * math.sin(ang) * cos_p
        pts.append((x, y))
    return pts


class _PathParser:
    def __init__(self, text: str, chord: float) -> None:
        self.tokens = list(_COMMAND.finditer(text))
        self.text = text
        self.chord = chord
        self.points: Poly = []
        self.cx = 0.0
        self.cy = 0.0
        self.sx = 0.0
        self.sy = 0.0
        self.last_cmd = ""
        self.ctrl: Vec2 | None = None

    def numbers_between(self, start: int, end: int) -> List[float]:
        return [float(n) for n in _NUMBER.findall(self.text[start:end])]

    def line_to(self, x: float, y: float) -> None:
        self.points.append((x, y))
        self.cx, self.cy = x, y
        self.ctrl = None

    def curve(self, x1: float, y1: float, x2: float, y2: float, x: float, y: float) -> None:
        steps = 8
        for i in range(1, steps + 1):
            t = i / steps
            mt = 1.0 - t
            px = mt**3 * self.cx + 3 * mt * mt * t * x1 + 3 * mt * t * t * x2 + t**3 * x
            py = mt**3 * self.cy + 3 * mt * mt * t * y1 + 3 * mt * t * t * y2 + t**3 * y
            self.points.append((px, py))
        self.cx, self.cy = x, y
        self.ctrl = (x2, y2)

    def quad(self, x1: float, y1: float, x: float, y: float) -> None:
        steps = 6
        for i in range(1, steps + 1):
            t = i / steps
            mt = 1.0 - t
            px = mt * mt * self.cx + 2 * mt * t * x1 + t * t * x
            py = mt * mt * self.cy + 2 * mt * t * y1 + t * t * y
            self.points.append((px, py))
        self.cx, self.cy = x, y
        self.ctrl = (x1, y1)

    def _keep(self, contours: List[Poly], closed: bool) -> None:
        pts = _dedupe(self.points)
        near = (
            len(pts) >= 3
            and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 0.05
        )
        if len(pts) >= 3 and (closed or near):
            contours.append(pts)

    def run(self) -> List[Poly]:
        contours: List[Poly] = []
        for index, match in enumerate(self.tokens):
            cmd = match.group(0)
            end = self.tokens[index + 1].start() if index + 1 < len(self.tokens) else len(self.text)
            nums = self.numbers_between(match.end(), end)
            self._command(cmd, nums, contours)
        self._keep(contours, False)
        return contours

    def _command(self, cmd: str, nums: List[float], contours: List[Poly]) -> None:
        rel = cmd.islower()
        kind = cmd.lower()
        if kind == "z":
            self._keep(contours, True)
            self.cx, self.cy = self.sx, self.sy
            self.points = []
            self.last_cmd = kind
            return
        if kind == "m":
            self._keep(contours, False)
            self.points = []
            pairs = list(zip(nums[0::2], nums[1::2]))
            if not pairs:
                return
            x, y = pairs[0]
            if rel:
                x += self.cx
                y += self.cy
            self.cx, self.cy = x, y
            self.sx, self.sy = x, y
            self.points = [(x, y)]
            for x, y in pairs[1:]:
                if rel:
                    x += self.cx
                    y += self.cy
                self.line_to(x, y)
            self.last_cmd = kind
            return
        if kind == "l":
            for x, y in zip(nums[0::2], nums[1::2]):
                if rel:
                    x += self.cx
                    y += self.cy
                self.line_to(x, y)
        elif kind == "h":
            for x in nums:
                if rel:
                    x += self.cx
                self.line_to(x, self.cy)
        elif kind == "v":
            for y in nums:
                if rel:
                    y += self.cy
                self.line_to(self.cx, y)
        elif kind == "c":
            for i in range(0, len(nums) - 5, 6):
                x1, y1, x2, y2, x, y = nums[i : i + 6]
                if rel:
                    x1 += self.cx
                    y1 += self.cy
                    x2 += self.cx
                    y2 += self.cy
                    x += self.cx
                    y += self.cy
                self.curve(x1, y1, x2, y2, x, y)
        elif kind == "s":
            for i in range(0, len(nums) - 3, 4):
                x2, y2, x, y = nums[i : i + 4]
                if rel:
                    x2 += self.cx
                    y2 += self.cy
                    x += self.cx
                    y += self.cy
                if self.last_cmd in ("c", "s") and self.ctrl is not None:
                    x1 = 2 * self.cx - self.ctrl[0]
                    y1 = 2 * self.cy - self.ctrl[1]
                else:
                    x1, y1 = self.cx, self.cy
                self.curve(x1, y1, x2, y2, x, y)
        elif kind == "q":
            for i in range(0, len(nums) - 3, 4):
                x1, y1, x, y = nums[i : i + 4]
                if rel:
                    x1 += self.cx
                    y1 += self.cy
                    x += self.cx
                    y += self.cy
                self.quad(x1, y1, x, y)
        elif kind == "t":
            for x, y in zip(nums[0::2], nums[1::2]):
                if rel:
                    x += self.cx
                    y += self.cy
                if self.last_cmd in ("q", "t") and self.ctrl is not None:
                    x1 = 2 * self.cx - self.ctrl[0]
                    y1 = 2 * self.cy - self.ctrl[1]
                else:
                    x1, y1 = self.cx, self.cy
                self.quad(x1, y1, x, y)
        elif kind == "a":
            for i in range(0, len(nums) - 6, 7):
                rx, ry, phi, large, sweep, x, y = nums[i : i + 7]
                if rel:
                    x += self.cx
                    y += self.cy
                pts = _flatten_arc(self.cx, self.cy, rx, ry, phi, bool(large), bool(sweep), x, y, self.chord)
                self.points.extend(pts)
                self.cx, self.cy = x, y
                self.ctrl = None
        self.last_cmd = kind


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _hidden(elem: ET.Element) -> bool:
    if (elem.get("display") or "").strip().lower() == "none":
        return True
    style = elem.get("style") or ""
    return "display:none" in style.replace(" ", "").lower()


def _sample_ellipse(cx: float, cy: float, rx: float, ry: float, chord: float) -> Poly:
    steps = max(12, min(80, int(math.ceil(2.0 * math.pi * max(rx, ry) / max(chord, 0.2)))))
    return [
        (cx + rx * math.cos(2.0 * math.pi * i / steps), cy + ry * math.sin(2.0 * math.pi * i / steps))
        for i in range(steps)
    ]


def _element_contours(elem: ET.Element, matrix: Tuple[float, ...], chord: float) -> List[Poly]:
    name = _local_name(elem.tag)
    if name == "path":
        contours = _PathParser(elem.get("d") or "", chord).run()
    elif name == "rect":
        x = _svg_length(elem.get("x"), 0.0) or 0.0
        y = _svg_length(elem.get("y"), 0.0) or 0.0
        w = _svg_length(elem.get("width"), 0.0) or 0.0
        h = _svg_length(elem.get("height"), 0.0) or 0.0
        rx = _svg_length(elem.get("rx"), 0.0) or 0.0
        ry = _svg_length(elem.get("ry"), 0.0) or 0.0
        if rx and not ry:
            ry = rx
        if ry and not rx:
            rx = ry
        if w <= 0 or h <= 0:
            return []
        local = _local_shape("roundrect" if rx or ry else "rect", w, h, min(rx, ry, w / 2.0, h / 2.0))
        # _local_shape is centered. A rect's corner is (x, y) in SVG, Y down.
        contours = [[(px + x + w / 2.0, py + y + h / 2.0) for px, py in local]]
    elif name == "circle":
        cx = _svg_length(elem.get("cx"), 0.0) or 0.0
        cy = _svg_length(elem.get("cy"), 0.0) or 0.0
        r = _svg_length(elem.get("r"), 0.0) or 0.0
        contours = [_sample_ellipse(cx, cy, r, r, chord)] if r > 0 else []
    elif name == "ellipse":
        cx = _svg_length(elem.get("cx"), 0.0) or 0.0
        cy = _svg_length(elem.get("cy"), 0.0) or 0.0
        rx = _svg_length(elem.get("rx"), 0.0) or 0.0
        ry = _svg_length(elem.get("ry"), 0.0) or 0.0
        contours = [_sample_ellipse(cx, cy, rx, ry, chord)] if rx > 0 and ry > 0 else []
    elif name == "polygon":
        nums = [float(n) for n in _NUMBER.findall(elem.get("points") or "")]
        contours = [list(zip(nums[0::2], nums[1::2]))]
    else:
        return []
    mapped: List[Poly] = []
    for contour in contours:
        pts = _dedupe([_apply(matrix, x, y) for x, y in contour])
        if len(pts) >= 3 and abs(_shoelace(pts)) > 0.05:
            mapped.append(pts)
    return mapped


def _walk_svg(elem: ET.Element, matrix: Tuple[float, ...], chord: float, found: List[Poly]) -> None:
    if _hidden(elem):
        return
    local = _multiply(matrix, _parse_transform(elem.get("transform")))
    name = _local_name(elem.tag)
    if name in ("g", "svg", "a", "symbol"):
        for child in list(elem):
            _walk_svg(child, local, chord, found)
        return
    found.extend(_element_contours(elem, local, chord))


def _resample(poly: Poly, limit: int) -> Poly:
    if len(poly) <= limit:
        return poly
    step = len(poly) / limit
    return [poly[int(i * step)] for i in range(limit)]


def parse_svg_outline(text: str) -> dict:
    """One closed outline from an SVG, centered, in millimetres.

    Raises ValueError with a message the form can show.
    """
    if len(text) > 200_000:
        raise ValueError("That SVG is too large.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("That file is not an SVG.") from exc
    if _local_name(root.tag) != "svg":
        raise ValueError("That file is not an SVG.")
    view = (root.get("viewBox") or "").replace(",", " ").split()
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    if len(view) == 4:
        try:
            min_x, min_y, vb_w, vb_h = (float(part) for part in view)
        except ValueError as exc:
            raise ValueError("The SVG view box is not usable.") from exc
        width = _svg_length(root.get("width"))
        height = _svg_length(root.get("height"))
        sx = width / vb_w if width and vb_w else 1.0
        sy = height / vb_h if height and vb_h else 1.0
        matrix = (sx, 0.0, 0.0, sy, -min_x * sx, -min_y * sy)
    found: List[Poly] = []
    _walk_svg(root, matrix, 0.35, found)
    if not found:
        raise ValueError("The SVG needs one closed shape.")
    found = [[(x, -y) for x, y in poly] for poly in found]
    found.sort(key=lambda poly: abs(_shoelace(poly)), reverse=True)
    outer = found[0]
    for extra in found[1:]:
        if not all(_point_in_poly(x, y, outer) for x, y in extra):
            raise ValueError("The SVG has more than one shape. Use a single closed outline.")
    outer = _dedupe(outer)
    if _self_intersects(outer):
        raise ValueError("That outline crosses itself.")
    outer = _resample(outer, 400)
    xs = [p[0] for p in outer]
    ys = [p[1] for p in outer]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width < _MIN_SIZE or height < _MIN_SIZE:
        raise ValueError("That outline is smaller than 2 mm.")
    points = [[round(x - cx, 3), round(y - cy, 3)] for x, y in outer]
    return {"points": points, "width": round(width, 3), "height": round(height, 3)}
