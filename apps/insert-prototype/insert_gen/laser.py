"""2D laser cut paths: finger-joint walls, divider slots, optional lid → SVG/DXF."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import ezdxf
import numpy as np
import svgwrite

from .model import Divider, InsertParams

Vec2 = Tuple[float, float]
Poly = List[Vec2]


@dataclass
class Panel:
    name: str
    outline: Poly
    holes: List[Poly]
    origin: Vec2  # placement in nest layout
    label: str = ""  # user name for a divider; blank uses Divider 1, Divider 2, …


def _rect(x: float, y: float, w: float, h: float) -> Poly:
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def _drop_collinear(poly: Poly, tol: float = 1e-8) -> Poly:
    """Drop repeated and in-line points so each remaining corner actually turns."""
    pts: Poly = []
    for point in poly:
        if not pts or abs(point[0] - pts[-1][0]) > 1e-9 or abs(point[1] - pts[-1][1]) > 1e-9:
            pts.append(point)
    if (
        len(pts) > 1
        and abs(pts[0][0] - pts[-1][0]) < 1e-9
        and abs(pts[0][1] - pts[-1][1]) < 1e-9
    ):
        pts.pop()
    guard = 0
    while len(pts) > 3 and guard < 8:
        guard += 1
        kept: Poly = []
        removed = False
        count = len(pts)
        for index in range(count):
            ax, ay = pts[(index - 1) % count]
            bx, by = pts[index]
            cx, cy = pts[(index + 1) % count]
            cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            if abs(cross) <= tol:
                removed = True
                continue
            kept.append(pts[index])
        pts = kept
        if not removed:
            break
    return pts


def _is_orthogonal(poly: Poly, tol: float = 1e-6) -> bool:
    count = len(poly)
    if count < 3:
        return False
    for index in range(count):
        x0, y0 = poly[index]
        x1, y1 = poly[(index + 1) % count]
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        if dx > tol and dy > tol:
            return False
    return True


def _segments_cross(a: Vec2, b: Vec2, c: Vec2, d: Vec2) -> bool:
    """True when the open segments AB and CD cross."""

    def cross(p: Vec2, q: Vec2, r: Vec2) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1 = cross(a, b, c)
    d2 = cross(a, b, d)
    d3 = cross(c, d, a)
    d4 = cross(c, d, b)
    if abs(d1) < 1e-8 or abs(d2) < 1e-8 or abs(d3) < 1e-8 or abs(d4) < 1e-8:
        return False
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def _self_intersects(poly: Poly) -> bool:
    count = len(poly)
    for i in range(count):
        a, b = poly[i], poly[(i + 1) % count]
        for j in range(i + 1, count):
            if j <= i + 1 or (i == 0 and j == count - 1):
                continue
            c, d = poly[j], poly[(j + 1) % count]
            if _segments_cross(a, b, c, d):
                return True
    return False


def _offset_orthogonal(poly: Poly, dist: float) -> Poly | None:
    """Move each axis-aligned edge by `dist` along its outward normal.

    Positive `dist` grows the part. A positive area is counter-clockwise.
    """
    pts = _drop_collinear(poly)
    if len(pts) < 3:
        return None
    area = _shoelace(pts)
    if abs(area) < 1e-6:
        return None
    winding = 1.0 if area > 0 else -1.0
    count = len(pts)
    lines: List[Tuple[str, float]] = []
    for index in range(count):
        x0, y0 = pts[index]
        x1, y1 = pts[(index + 1) % count]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return None
        ox = winding * dy / length
        oy = winding * -dx / length
        if abs(dy) <= abs(dx):
            lines.append(("h", y0 + oy * dist))
        else:
            lines.append(("v", x0 + ox * dist))
    out: Poly = []
    for index in range(count):
        previous = lines[(index - 1) % count]
        current = lines[index]
        if previous[0] == current[0]:
            return None
        if previous[0] == "v":
            out.append((previous[1], current[1]))
        else:
            out.append((current[1], previous[1]))
    if _self_intersects(out) or abs(_shoelace(out)) < 1.0:
        return None
    return out


def _offset_bbox(poly: Poly, kerf: float, outward: bool) -> Poly:
    """Expand or shrink by the bounding-box center. Used when an edge is diagonal."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    half = kerf / 2.0 * (1.0 if outward else -1.0)
    out: Poly = []
    for x, y in poly:
        dx = half if x >= cx else -half
        dy = half if y >= cy else -half
        out.append((x + dx, y + dy))
    return out


def _offset_kerf(poly: Poly, kerf: float, outward: bool = True) -> Poly:
    """Grow or shrink a cut path by half the kerf.

    Axis-aligned outlines, including finger joints, are offset edge by edge so a
    tab grows by the kerf and the gap it fits into shrinks by the kerf. A diagonal
    edge keeps the older bounding-box expansion.
    """
    if kerf <= 0 or len(poly) < 3:
        return list(poly)
    dist = kerf / 2.0 if outward else -kerf / 2.0
    cleaned = _drop_collinear(poly)
    if len(cleaned) >= 3 and _is_orthogonal(cleaned):
        shifted = _offset_orthogonal(cleaned, dist)
        if shifted:
            return shifted
    return _offset_bbox(poly, kerf, outward)


def _finger_edge(
    length: float,
    thickness: float,
    fingers: int,
    male: bool,
    kerf: float,
) -> List[Tuple[float, float]]:
    """Return 2D polyline for a finger-jointed edge along +X, starting at (0,0), going to (length,0).

    `male` starts with a protruding finger; female starts with a notch.
    Y positive is into the panel. Returns points along the joint edge only
    (y = 0 or y = ±thickness depending on male/female notches).
    """
    # Compensate kerf so fingers fit: male fingers slightly smaller, female notches slightly larger
    # For outline cuts we expand male valleys / shrink male fingers via kerf on the whole panel.
    n = fingers
    if n % 2 == 0:
        n += 1  # odd count so both ends match (female ends with notch-friendly pattern)
    seg = length / n
    pts: List[Tuple[float, float]] = []
    # Walk along X; for male, odd segments protrude (y negative = out of panel if panel is +Y)
    # Convention: panel body is y>0; fingers protrude to y<0 for male.
    for i in range(n):
        x0 = i * seg
        x1 = (i + 1) * seg
        is_finger = (i % 2 == 0) if male else (i % 2 == 1)
        if i == 0:
            pts.append((x0, 0.0 if not is_finger else -thickness))
        if is_finger:
            # step down, across, up
            pts.append((x0, -thickness))
            pts.append((x1, -thickness))
            pts.append((x1, 0.0))
        else:
            pts.append((x0, 0.0))
            pts.append((x1, 0.0))
    # Ensure last point at length
    if pts[-1][0] != length:
        pts.append((length, pts[-1][1]))
    return pts


def _midpoint_edge(length: float, thickness: float, male: bool) -> List[Tuple[float, float]]:
    """One joint at the middle. Male owns the first half; female owns the second."""
    mid = length / 2.0
    if male:
        return [(0.0, -thickness), (mid, -thickness), (mid, 0.0), (length, 0.0)]
    return [(0.0, 0.0), (mid, 0.0), (mid, -thickness), (length, -thickness)]


def _lid_corner_count(edge_h: float, wall_pitch: float) -> int:
    """Odd finger count at the box-corner pitch, or 1 for a joint at the middle.

    A lid side shorter than three box-corner fingers cannot carry that joint,
    so the two sides meet once, halfway along the edge.
    """
    if wall_pitch <= 1e-6 or edge_h < 3.0 * wall_pitch - 1e-6:
        return 1
    count = int(round(edge_h / wall_pitch))
    if count % 2 == 0:
        lower = max(1, count - 1)
        upper = count + 1
        count = lower if abs(edge_h / lower - wall_pitch) <= abs(edge_h / upper - wall_pitch) else upper
    if count < 3 or edge_h / count < wall_pitch * 0.75:
        return 1
    return count


def _top_polyline(
    length: float, depth: float, spans: List[Tuple[float, float]], height: float
) -> Poly:
    """Top edge, right to left. Fingers stay at the wall top; gaps drop by `depth`."""
    edge = [(x, height - y) for x, y in _bottom_polyline(length, depth, spans)]
    edge.reverse()
    return edge


def _wall_panel_outline(
    length: float,
    height: float,
    thickness: float,
    fingers: int,
    left_male: bool,
    right_male: bool,
    floor_fingers: List[Tuple[float, float]] | None = None,
    corner_count: int | None = None,
    left_joint: float | None = None,
    right_joint: float | None = None,
    top_fingers: List[Tuple[float, float]] | None = None,
) -> Poly:
    """Wall panel in local coords: length along X, height along Y.

    Left and right edges are the corner joints. When `floor_fingers` is set, those
    joints start at the top of the floor and the bottom edge fingers pass through it.
    Fingers sit at y=0; the gaps between them rise to y=thickness so the wall sits
    on the floor there. `corner_count` overrides how many fingers run up the
    short edges. A count of 1 is a single joint at the middle of that edge.
    `left_joint` and `right_joint` stop the fingers early when the neighbouring
    wall is shorter. The rest of that end rises straight to `height`.
    `top_fingers` uses the same spans as the floor, so a closed lid matches the
    bottom. Corner fingers stop at the underside of that lid.
    """

    def corner_raw(span: float, male: bool) -> List[Tuple[float, float]]:
        if corner_count is not None and corner_count <= 1:
            return _midpoint_edge(span, thickness, male)
        n = fingers if corner_count is None else corner_count
        return _finger_edge(span, thickness, n, male, 0.0)

    cap = height - thickness if top_fingers else None

    def rising(joint: float | None, male: bool, at_right: bool, y0: float) -> Poly:
        limit = height if joint is None else min(height, max(y0, joint))
        if cap is not None:
            limit = min(limit, cap)
        edge_h = limit - y0
        root = length if at_right else 0.0
        if edge_h < 1.0:
            end = height if cap is None else limit
            return [(root, y0), (root, end)] if at_right else [(root, end), (root, y0)]
        raw = corner_raw(edge_h, male)
        if at_right:
            pts = [(length - y, x + y0) for x, y in raw]
            if floor_fingers and (abs(pts[0][0] - length) > 1e-9 or abs(pts[0][1] - y0) > 1e-9):
                pts.insert(0, (length, y0))
            if cap is None and height > limit + 1e-6:
                if abs(pts[-1][0] - root) > 1e-6:
                    pts.append((root, pts[-1][1]))
                pts.append((root, height))
            return pts
        pts_up = [(y, x + y0) for x, y in raw]
        if floor_fingers and (abs(pts_up[0][0]) > 1e-9 or abs(pts_up[0][1] - y0) > 1e-9):
            pts_up.insert(0, (0.0, y0))
        if cap is None and height > limit + 1e-6:
            if abs(pts_up[-1][0] - root) > 1e-6:
                pts_up.append((root, pts_up[-1][1]))
            pts_up.append((root, height))
        return list(reversed(pts_up))

    y0 = thickness if floor_fingers else 0.0
    if floor_fingers:
        bottom = _bottom_polyline(length, thickness, floor_fingers)
    else:
        bottom = [(0.0, 0.0), (length, 0.0)]
    right = rising(right_joint, right_male, True, y0)
    if top_fingers:
        top = _top_polyline(length, thickness, top_fingers, height)
    else:
        top = [(length, height), (0.0, height)]
    left = rising(left_joint, left_male, False, y0)
    outline: Poly = []
    _append_unique(outline, bottom)
    _append_unique(outline, right)
    _append_unique(outline, top)
    _append_unique(outline, left)
    return outline


def _odd_count(n: int) -> int:
    return n if n % 2 else n + 1


def _finger_spans(length: float, count: int, male: bool = True) -> List[Tuple[float, float]]:
    """Intervals along an edge that are fingers. Count is forced odd so both ends match."""
    n = max(1, _odd_count(count))
    seg = length / n
    spans: List[Tuple[float, float]] = []
    for i in range(n):
        is_finger = (i % 2 == 0) if male else (i % 2 == 1)
        if is_finger:
            spans.append((i * seg, (i + 1) * seg))
    return spans


def _spans_for_length(length: float, pitch: float) -> List[Tuple[float, float]]:
    """Finger spans sized to `pitch`, with an odd count so both ends are fingers."""
    if length < 1e-6:
        return []
    count = max(1, int(round(length / pitch))) if pitch > 1e-6 else 1
    return _finger_spans(length, count, male=True)


def _bottom_polyline(length: float, depth: float, spans: List[Tuple[float, float]]) -> Poly:
    """Bottom edge, left to right. Fingers stay at y=0; gaps rise to y=depth."""
    pts: Poly = []

    def add(x: float, y: float) -> None:
        if not pts or abs(pts[-1][0] - x) > 1e-9 or abs(pts[-1][1] - y) > 1e-9:
            pts.append((x, y))

    x = 0.0
    for a, b in spans:
        if a > x + 1e-9:
            add(x, depth)
            add(a, depth)
            add(a, 0.0)
        else:
            add(x, 0.0)
        add(b, 0.0)
        x = b
    if x < length - 1e-9:
        add(x, depth)
        add(length, depth)
    else:
        add(length, 0.0)
    return pts


def _merge_spans(spans: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    ordered = sorted((a, b) for a, b in spans if b > a + 1e-9)
    if not ordered:
        return []
    merged: List[List[float]] = [[ordered[0][0], ordered[0][1]]]
    for a, b in ordered[1:]:
        if a <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _cover_corners(
    spans: List[Tuple[float, float]], length: float, corner: float
) -> List[Tuple[float, float]]:
    """Make sure the first and last `corner` of an edge are fingers."""
    if corner <= 1e-6 or length <= 1e-6:
        return spans
    cap = min(corner, length)
    return _merge_spans(list(spans) + [(0.0, cap), (max(0.0, length - cap), length)])


def _floor_joint_spans(
    length: float, thickness: float, pitch: float, owns_corners: bool
) -> List[Tuple[float, float]]:
    """Where a wall's bottom fingers pass through the floor, measured along the wall.

    Front and back own the corners. The side walls are fingered only between them
    so the corner squares are cut once.
    """
    if length <= thickness * 2.0 + 1.0:
        return []
    if owns_corners:
        return _cover_corners(_spans_for_length(length, pitch), length, thickness)
    inner = length - 2.0 * thickness
    return [(a + thickness, b + thickness) for a, b in _spans_for_length(inner, pitch)]


def _complement_spans(length: float, spans: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    gaps: List[Tuple[float, float]] = []
    x = 0.0
    for a, b in spans:
        if a > x + 1e-6:
            gaps.append((x, a))
        x = max(x, b)
    if length - x > 1e-6:
        gaps.append((x, length))
    return gaps


def _clip_polyline_x(pts: Poly, lo: float, hi: float) -> Poly:
    """Keep the part of a polyline whose first coordinate lies in [lo, hi]."""
    if len(pts) < 2:
        return [p for p in pts if lo - 1e-6 <= p[0] <= hi + 1e-6]
    kept: Poly = []

    def add(x: float, y: float) -> None:
        if lo - 1e-6 <= x <= hi + 1e-6:
            if not kept or abs(kept[-1][0] - x) > 1e-9 or abs(kept[-1][1] - y) > 1e-9:
                kept.append((x, y))

    def inside(x: float) -> bool:
        return lo - 1e-9 <= x <= hi + 1e-9

    def lerp(a: Vec2, b: Vec2, x: float) -> Vec2:
        ax, ay = a
        bx, by = b
        if abs(bx - ax) < 1e-12:
            return (x, ay)
        t = (x - ax) / (bx - ax)
        return (x, ay + (by - ay) * t)

    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        if inside(a[0]):
            add(a[0], a[1])
        if abs(b[0] - a[0]) > 1e-12:
            crossings = []
            for edge in (lo, hi):
                t = (edge - a[0]) / (b[0] - a[0])
                if 1e-9 < t < 1.0 - 1e-9:
                    crossings.append((t, edge))
            for _, edge in sorted(crossings):
                x, y = lerp(a, b, edge)
                add(x, y)
        if i == len(pts) - 2 and inside(b[0]):
            add(b[0], b[1])
    return kept


def _floor_outline(
    length: float,
    width: float,
    thickness: float,
    length_spans: List[Tuple[float, float]],
    width_spans: List[Tuple[float, float]],
) -> Poly:
    """Floor plate. Notches along each edge are open where a wall finger passes through.

    Front and back notches include the corners. Side notches run between the walls,
    so each corner is removed once and the outline turns at the inner corner.
    """
    t = thickness
    front = _clip_polyline_x(
        _bottom_polyline(length, t, _complement_spans(length, length_spans)),
        t,
        length - t,
    )
    back = _clip_polyline_x(
        _bottom_polyline(length, t, _complement_spans(length, length_spans)),
        t,
        length - t,
    )
    inner = width - 2.0 * t
    local_side: List[Tuple[float, float]] = []
    for a, b in width_spans:
        aa = max(0.0, a - t)
        bb = min(inner, b - t)
        if bb > aa + 1e-6:
            local_side.append((aa, bb))
    side = _bottom_polyline(inner, t, _complement_spans(inner, local_side))

    outline: Poly = []
    _append_unique(outline, front)
    _append_unique(outline, [(length - inset, t + along) for along, inset in side])
    _append_unique(outline, [(x, width - inset) for x, inset in reversed(back)])
    _append_unique(outline, [(inset, t + along) for along, inset in reversed(side)])
    if (
        outline
        and abs(outline[0][0] - outline[-1][0]) < 1e-9
        and abs(outline[0][1] - outline[-1][1]) < 1e-9
    ):
        outline.pop()
    return outline


def _divider_length(d: Divider) -> float:
    return float(np.hypot(d.x2 - d.x1, d.y2 - d.y1))


def _slot_along_centerline(
    d: Divider,
    t0: float,
    t1: float,
    thickness: float,
    kerf: float,
) -> Poly:
    """Rectangle across the divider centerline from distance t0 to t1."""
    length = _divider_length(d)
    if length < 1e-6 or t1 <= t0:
        return []
    ux, uy = (d.x2 - d.x1) / length, (d.y2 - d.y1) / length
    nx, ny = -uy, ux
    half = (thickness + kerf) / 2.0
    a = max(0.0, t0 - kerf / 2.0)
    b = min(length, t1 + kerf / 2.0)
    if b <= a:
        return []

    def p(t: float, s: float) -> Vec2:
        return (d.x1 + ux * t + nx * s, d.y1 + uy * t + ny * s)

    return [p(a, -half), p(b, -half), p(b, half), p(a, half)]


@dataclass
class _DivJoint:
    """How this divider meets another divider.

    `t` is the distance along this centerline to the joint. `width` is the opening
    along this divider. A stub is an end of this divider; `at_start` marks x1, y1.
    """

    kind: str  # cross-bottom, cross-top, stub, slot, lean-slot, lean-stub, lean-finger
    t: float
    width: float
    square: bool = True
    at_start: bool = False
    y0: float = 0.0  # low world-Y of the removed band or the finger span
    y1: float = 0.0
    # For a joint on a tilted face: how far the mating midplane moves along this
    # centerline per millimetre of world height, and the world height where that
    # shift is zero (the mating plate's bottom).
    slope: float = 0.0
    anchor: float = 0.0
    # Two stubs from opposite sides share one slot. Each tab stops at the midplane.
    half: bool = False


def _unit_dir(d: Divider) -> Tuple[float, float, float]:
    length = _divider_length(d)
    if length < 1e-6:
        return 0.0, 0.0, 0.0
    return (d.x2 - d.x1) / length, (d.y2 - d.y1) / length, length


def _dist_to_segment(px: float, py: float, d: Divider) -> Tuple[float, float]:
    """Distance from a point to a divider centerline, and the distance along it."""
    ux, uy, length = _unit_dir(d)
    if length < 1e-6:
        return float(np.hypot(px - d.x1, py - d.y1)), 0.0
    t = (px - d.x1) * ux + (py - d.y1) * uy
    tc = min(max(t, 0.0), length)
    return float(np.hypot(px - (d.x1 + ux * tc), py - (d.y1 + uy * tc))), tc


def _end_is_wall(x: float, y: float, ox: float, oy: float, params: InsertParams) -> bool:
    return (
        _square_wall_hit(x, y, ox, oy, params) is not None
        or _loose_wall_hit(x, y, params) is not None
    )


def _plate_overlap(
    a: Divider, b: Divider, params: InsertParams
) -> Tuple[float, float] | None:
    """World-Y overlap of two divider plates. None when they do not meet in height."""
    sa = a.plate_span(params.height, params.thickness, params.floor, params.closed_top())
    sb = b.plate_span(params.height, params.thickness, params.floor, params.closed_top())
    if sa is None or sb is None:
        return None
    lo = max(sa[0], sb[0])
    hi = min(sa[1], sb[1])
    if hi < lo + 1.0:
        return None
    return lo, hi


def _finger_interval(d: Divider, params: InsertParams) -> Tuple[float, float] | None:
    """World-Y of the standing edge, above the floor joint."""
    span = d.plate_span(params.height, params.thickness, params.floor, params.closed_top())
    if span is None:
        return None
    floor_top = params.thickness if params.floor else 0.0
    lo = max(span[0], floor_top)
    hi = span[1]
    if hi < lo + 1.0:
        return None
    return lo, hi


def _into_face_sign(ox: float, oy: float, thru: Divider) -> float:
    """Which side of `thru` this direction approaches. Opposite ends have opposite signs."""
    norm = math.hypot(ox, oy)
    ux, uy, length = _unit_dir(thru)
    if norm < 1e-6 or length < 1e-6:
        return 0.0
    nx, ny = -uy, ux
    return (ox / norm) * nx + (oy / norm) * ny


def _share_opposite_stub(
    joints: List[List[_DivJoint]],
    divs: List[Divider],
    thru: Divider,
    thru_i: int,
    tc: float,
    px: float,
    py: float,
    outward: Tuple[float, float],
    thickness: float,
    tol: float,
) -> _DivJoint | None:
    """Share an existing finger slot with a stub arriving from the other side.

    Marks the slot and the stub already using it as half depth, and returns the
    slot. Same-side arrivals are left alone.
    """
    slot = next(
        (
            item
            for item in joints[thru_i]
            if item.kind in ("slot", "lean-finger") and abs(item.t - tc) < thickness
        ),
        None,
    )
    if slot is None:
        return None
    new_sign = _into_face_sign(outward[0], outward[1], thru)
    if abs(new_sign) < 0.2:
        return None
    other: _DivJoint | None = None
    for div, owned in zip(divs, joints):
        for item in owned:
            if item.kind not in ("stub", "lean-stub") or not item.square:
                continue
            ex, ey = (div.x1, div.y1) if item.at_start else (div.x2, div.y2)
            if math.hypot(ex - px, ey - py) > tol:
                continue
            away = (div.x1 - div.x2, div.y1 - div.y2) if item.at_start else (div.x2 - div.x1, div.y2 - div.y1)
            old_sign = _into_face_sign(away[0], away[1], thru)
            if new_sign * old_sign < -0.05:
                other = item
                break
        if other is not None:
            break
    if other is None:
        return None
    other.half = True
    slot.half = True
    return slot


def _plate_anchor(d: Divider, params: InsertParams) -> float:
    """World height the lean pivots about: the bottom of this divider's plate."""
    span = d.plate_span(params.height, params.thickness, params.floor, params.closed_top())
    return span[0] if span is not None else 0.0


def _lean_pair_joints(
    joints: List[List[_DivJoint]],
    i: int,
    j: int,
    a: Divider,
    b: Divider,
    params: InsertParams,
    la: float,
    lb: float,
    ta: float,
    tb: float,
    sin_th: float,
    lo: float,
    hi: float,
    thickness: float,
    margin: float,
    tol: float,
) -> None:
    """Overlap or tee when at least one divider leans.

    A crossing still splits the shared height. A square tee is a finger joint
    perpendicular to the through piece: the stub's end follows that face and
    its fingers run along the face normal. A meeting that is not square in
    plan keeps one slot.
    """
    cos_a = max(0.2, abs(math.cos(a.tilt_radians())))
    cos_b = max(0.2, abs(math.cos(b.tilt_radians())))
    width_a = thickness / cos_b / sin_th
    width_b = thickness / cos_a / sin_th
    if 0.0 <= ta <= 1.0 and 0.0 <= tb <= 1.0:
        da, db = ta * la, tb * lb
        if margin < da < la - margin and margin < db < lb - margin:
            mid = (lo + hi) / 2.0
            joints[i].append(_DivJoint("cross-bottom", da, width_a, y0=lo, y1=mid))
            joints[j].append(_DivJoint("cross-top", db, width_b, y0=mid, y1=hi))
            return
    uax, uay, _ = _unit_dir(a)
    ubx, uby, _ = _unit_dir(b)
    square = abs(uax * ubx + uay * uby) <= 0.53
    finger_w = thickness / sin_th
    ends = (
        (0.0, a.x1, a.y1, a.x2, a.y2, i, a, uax, uay, j, b, lb, True),
        (la, a.x2, a.y2, a.x1, a.y1, i, a, uax, uay, j, b, lb, False),
        (0.0, b.x1, b.y1, b.x2, b.y2, j, b, ubx, uby, i, a, la, True),
        (lb, b.x2, b.y2, b.x1, b.y1, j, b, ubx, uby, i, a, la, False),
    )
    for stub_t, px, py, ox, oy, stub_i, stub, sux, suy, thru_i, thru, thru_len, at_start in ends:
        if _end_is_wall(px, py, ox, oy, params):
            continue
        dist, tc = _dist_to_segment(px, py, thru)
        if dist > tol or not (margin < tc < thru_len - margin):
            continue
        if any(item.kind == "lean-stub" and item.at_start == at_start for item in joints[stub_i]):
            return
        fa = _finger_interval(stub, params)
        fb = _finger_interval(thru, params)
        if square:
            shared = _share_opposite_stub(
                joints,
                params.dividers,
                thru,
                thru_i,
                tc,
                px,
                py,
                (px - ox, py - oy),
                thickness,
                thickness,
            )
            if shared is not None:
                tux, tuy, _ = _unit_dir(thru)
                tnx, tny = -tuy, tux
                slope_stub = (tnx * sux + tny * suy) * math.tan(thru.tilt_radians())
                joints[stub_i].append(
                    _DivJoint(
                        "lean-stub",
                        stub_t,
                        finger_w,
                        True,
                        at_start,
                        shared.y0,
                        shared.y1,
                        slope_stub,
                        _plate_anchor(thru, params),
                        True,
                    )
                )
                return
        if any(item.kind in ("lean-slot", "lean-finger") and abs(item.t - tc) < thickness for item in joints[thru_i]):
            return
        if square and fa is not None and fb is not None:
            flo = max(fa[0], fb[0])
            fhi = min(fa[1], fb[1])
            if fhi >= flo + 1.0:
                tux, tuy, _ = _unit_dir(thru)
                tnx, tny = -tuy, tux
                snx, sny = -suy, sux
                slope_stub = (tnx * sux + tny * suy) * math.tan(thru.tilt_radians())
                slope_thru = (snx * tux + sny * tuy) * math.tan(stub.tilt_radians())
                joints[stub_i].append(
                    _DivJoint(
                        "lean-stub",
                        stub_t,
                        finger_w,
                        True,
                        at_start,
                        flo,
                        fhi,
                        slope_stub,
                        _plate_anchor(thru, params),
                    )
                )
                joints[thru_i].append(
                    _DivJoint(
                        "lean-finger",
                        tc,
                        finger_w,
                        True,
                        False,
                        flo,
                        fhi,
                        slope_thru,
                        _plate_anchor(stub, params),
                    )
                )
                return
        y_lo = lo + thickness
        y_hi = hi - thickness
        if y_hi < y_lo + 2.0:
            return
        joints[thru_i].append(_DivJoint("lean-slot", tc, thickness / sin_th, y0=y_lo, y1=y_hi))
        return


def _divider_joints(params: InsertParams) -> List[List[_DivJoint]]:
    """Cross-laps where dividers pass through each other, finger joints where one ends on another.

    The earlier divider is slotted up from the bottom; the later one is slotted down
    from the top. The lap is the middle of the heights they share. An end that already
    meets a wall is left to that wall joint.
    """
    divs = params.dividers
    joints: List[List[_DivJoint]] = [[] for _ in divs]
    thickness = params.thickness
    margin = max(thickness, 2.0)
    tol = 1.5
    for i in range(len(divs)):
        for j in range(i + 1, len(divs)):
            a, b = divs[i], divs[j]
            uax, uay, la = _unit_dir(a)
            ubx, uby, lb = _unit_dir(b)
            if la < 1e-6 or lb < 1e-6:
                continue
            sin_th = abs(uax * uby - uay * ubx)
            if sin_th < 0.25:
                continue
            overlap = _plate_overlap(a, b, params)
            if overlap is None:
                continue
            lo, hi = overlap
            rx, ry = a.x2 - a.x1, a.y2 - a.y1
            sx, sy = b.x2 - b.x1, b.y2 - b.y1
            denom = rx * sy - ry * sx
            if abs(denom) < 1e-8:
                continue
            qpx, qpy = b.x1 - a.x1, b.y1 - a.y1
            ta = (qpx * sy - qpy * sx) / denom
            tb = (qpx * ry - qpy * rx) / denom
            square = abs(uax * ubx + uay * uby) <= 0.53
            width = thickness / sin_th
            if a.leans() or b.leans():
                _lean_pair_joints(
                    joints, i, j, a, b, params, la, lb, ta, tb, sin_th, lo, hi, thickness, margin, tol
                )
                continue
            if 0.0 <= ta <= 1.0 and 0.0 <= tb <= 1.0:
                da, db = ta * la, tb * lb
                if margin < da < la - margin and margin < db < lb - margin:
                    mid = (lo + hi) / 2.0
                    joints[i].append(_DivJoint("cross-bottom", da, width, y0=lo, y1=mid))
                    joints[j].append(_DivJoint("cross-top", db, width, y0=mid, y1=hi))
                    continue
            fa = _finger_interval(a, params)
            fb = _finger_interval(b, params)
            if fa is None or fb is None:
                continue
            flo = max(fa[0], fb[0])
            fhi = min(fa[1], fb[1])
            if fhi < flo + 1.0:
                continue
            ends = (
                (i, 0.0, a.x1, a.y1, a.x2, a.y2, j, b, lb),
                (i, la, a.x2, a.y2, a.x1, a.y1, j, b, lb),
                (j, 0.0, b.x1, b.y1, b.x2, b.y2, i, a, la),
                (j, lb, b.x2, b.y2, b.x1, b.y1, i, a, la),
            )
            for stub_i, stub_t, px, py, ox, oy, thru_i, thru, thru_len in ends:
                if _end_is_wall(px, py, ox, oy, params):
                    continue
                dist, tc = _dist_to_segment(px, py, thru)
                if dist > tol or not (margin < tc < thru_len - margin):
                    continue
                at_start = stub_t < 1e-6
                if any(item.kind == "stub" and item.at_start == at_start for item in joints[stub_i]):
                    continue
                if square:
                    shared = _share_opposite_stub(
                        joints,
                        divs,
                        thru,
                        thru_i,
                        tc,
                        px,
                        py,
                        (px - ox, py - oy),
                        thickness,
                        thickness,
                    )
                    if shared is not None:
                        joints[stub_i].append(
                            _DivJoint("stub", stub_t, width, True, at_start, shared.y0, shared.y1, half=True)
                        )
                        break
                if any(item.kind == "slot" and abs(item.t - tc) < thickness for item in joints[thru_i]):
                    continue
                joints[stub_i].append(
                    _DivJoint("stub", stub_t, width, square, at_start, flo, fhi)
                )
                joints[thru_i].append(_DivJoint("slot", tc, width, square, y0=flo, y1=fhi))
                break
    return joints


def _end_insets(span: float, joints: List[_DivJoint], thickness: float) -> Tuple[float, float]:
    """Pull a square stub back to the near face of the divider it fingers into."""
    left = 0.0
    right = 0.0
    inset = thickness / 2.0
    for joint in joints:
        if joint.kind == "stub" and joint.square:
            if joint.at_start:
                left = inset
            else:
                right = inset
    if span - left - right < 1.0:
        return 0.0, 0.0
    return left, right


def _floor_finger_limits(
    length: float, joints: List[_DivJoint], thickness: float
) -> Tuple[float, float]:
    """Centerline interval that carries floor fingers.

    Square stubs and angled stubs into another divider are pulled back by half
    the thickness so the floor slots stop at that joint.
    """
    left, right = _end_insets(length, joints, thickness)
    inset = thickness / 2.0
    for joint in joints:
        if joint.kind == "lean-stub" and joint.square:
            if joint.at_start:
                left = max(left, inset)
            else:
                right = max(right, inset)
    if length - left - right < 1.0:
        return 0.0, length
    return left, length - right


def _notch_intervals(
    joints: List[_DivJoint], kind: str, kerf: float, y_open: float | None = None
) -> List[Tuple[float, float]]:
    spans: List[Tuple[float, float]] = []
    for joint in joints:
        if joint.kind != kind:
            continue
        if y_open is not None and abs(joint.y0 - y_open) > 0.75:
            continue
        half = (joint.width + kerf) / 2.0
        spans.append((joint.t - half, joint.t + half))
    return spans


def _body_notches(
    joints: List[_DivJoint],
    kind: str,
    kerf: float,
    left_inset: float,
    body: float,
    plate_y0: float,
    plate_y1: float,
) -> List[Tuple[float, float, float]]:
    """Cross-lap notches that open through an edge: (x0, x1, reach Y).

    A lap that starts above this plate's bottom, or stops below its top, is a
    closed slot instead and is left out of the outline.
    """
    spans: List[Tuple[float, float, float]] = []
    for joint in joints:
        if joint.kind != kind:
            continue
        if kind == "cross-bottom" and abs(joint.y0 - plate_y0) <= 0.75:
            reach = joint.y1
        elif kind == "cross-top" and abs(joint.y1 - plate_y1) <= 0.75:
            reach = joint.y0
        else:
            continue
        half = (joint.width + kerf) / 2.0
        aa = max(0.0, joint.t - half - left_inset)
        bb = min(body, joint.t + half - left_inset)
        if bb > aa + 0.2:
            spans.append((aa, bb, reach))
    return spans


def _clip_slot_x(local: float, width: float, body: float) -> Tuple[float, float] | None:
    sx = local - width / 2.0
    sw = width
    if sx < 0.0:
        sw += sx
        sx = 0.0
    if sx + sw > body:
        sw = body - sx
    if sw <= 0.5:
        return None
    return sx, sw


def _tee_holes(
    joints: List[_DivJoint],
    left_inset: float,
    body: float,
    height: float,
    thickness: float,
    kerf: float,
    finger_pitch: float,
    floor: bool,
) -> List[Poly]:
    """Slots in a through-divider for a divider that ends on it.

    The slots cover only the height the two dividers share.
    """
    holes: List[Poly] = []
    floor_top = thickness if floor else 0.0
    for joint in joints:
        if joint.kind != "slot":
            continue
        local = joint.t - left_inset
        full = abs(joint.y0 - floor_top) < 1e-6 and abs(joint.y1 - height) < 1e-6
        if joint.square:
            holes.extend(
                _finger_slots_between(
                    local,
                    body,
                    thickness,
                    kerf,
                    joint.y0,
                    joint.y1,
                    finger_pitch,
                    y_min=floor_top,
                )
            )
            continue
        sw = joint.width + kerf
        if full:
            y0 = floor_top if floor_top > 0.0 else 0.5
            y1 = height - 1.0
        else:
            y0 = joint.y0 + 1.0
            y1 = joint.y1 - 1.0
        placed = _clip_slot_x(local, sw, body)
        if placed and y1 > y0:
            holes.append(_rect(placed[0], y0, placed[1], y1 - y0))
    return holes


def _closed_cross_holes(
    joints: List[_DivJoint],
    left_inset: float,
    body: float,
    plate_y0: float,
    plate_y1: float,
    kerf: float,
) -> List[Poly]:
    """Cross-lap slots that do not open through the top or bottom edge."""
    holes: List[Poly] = []
    for joint in joints:
        if joint.kind == "cross-bottom":
            if abs(joint.y0 - plate_y0) <= 0.75:
                continue
        elif joint.kind == "cross-top":
            if abs(joint.y1 - plate_y1) <= 0.75:
                continue
        else:
            continue
        placed = _clip_slot_x(joint.t - left_inset, joint.width + kerf, body)
        if not placed:
            continue
        y0 = max(plate_y0, joint.y0 - kerf / 2.0)
        y1 = min(plate_y1, joint.y1 + kerf / 2.0)
        if y1 > y0 + 0.5:
            holes.append(_rect(placed[0], y0, placed[1], y1 - y0))
    return holes


def _lean_slot_holes(
    joints: List[_DivJoint],
    left_inset: float,
    body: float,
    plate_y0: float,
    cos_a: float,
    kerf: float,
) -> List[Poly]:
    """Plain slots where a leaned divider ends on this one."""
    holes: List[Poly] = []
    scale = cos_a if abs(cos_a) > 1e-6 else 1.0
    for joint in joints:
        if joint.kind != "lean-slot":
            continue
        placed = _clip_slot_x(joint.t - left_inset, joint.width + kerf, body)
        if not placed:
            continue
        y0 = (joint.y0 - plate_y0) / scale
        y1 = (joint.y1 - plate_y0) / scale
        if y1 > y0 + 0.5:
            holes.append(_rect(placed[0], y0, placed[1], y1 - y0))
    return holes


def _subtract_spans(
    spans: List[Tuple[float, float]], cuts: List[Tuple[float, float]]
) -> List[Tuple[float, float]]:
    parts = list(spans)
    for c0, c1 in cuts:
        nxt: List[Tuple[float, float]] = []
        for a, b in parts:
            if c1 <= a or c0 >= b:
                nxt.append((a, b))
                continue
            if a < c0 - 1e-9:
                nxt.append((a, c0))
            if c1 < b - 1e-9:
                nxt.append((c1, b))
        parts = nxt
    return [(a, b) for a, b in parts if b > a + 1e-6]


def _divider_finger_slots_on_floor(
    d: Divider,
    params: InsertParams,
    joints: List[_DivJoint] | None = None,
    notch_kind: str = "cross-bottom",
    y_open: float = 0.0,
) -> List[Poly]:
    """Finger slots through the floor. Gaps between fingers stay solid so the divider sits on them.

    The span stops at the face of a divider this one fingers into, and skips a cross-lap
    that is cut up from the bottom.
    """
    length = _divider_length(d)
    if length < 1e-6:
        return []
    owned = joints or []
    t0, t1 = _floor_finger_limits(length, owned, params.thickness)
    pitch = params.height / _odd_count(params.finger_count)
    spans = [(a + t0, b + t0) for a, b in _spans_for_length(t1 - t0, pitch)]
    spans = _subtract_spans(
        spans, _notch_intervals(owned, notch_kind, params.kerf, y_open=y_open)
    )
    holes: List[Poly] = []
    for a, b in spans:
        if b - a < 1.0:
            continue
        slot = _slot_along_centerline(d, a, b, params.thickness, params.kerf)
        if slot:
            holes.append(slot)
    return holes


def _square_wall_hit(
    x: float,
    y: float,
    ox: float,
    oy: float,
    params: InsertParams,
) -> Tuple[str, float] | None:
    """Return (wall name, position along that wall) when this end meets a wall squarely.

    `(ox, oy)` is the other end. The divider must run about perpendicular to the wall,
    inward from either the outer face or the inner face.
    """
    L, W, T = params.outer_length, params.outer_width, params.thickness
    dx, dy = ox - x, oy - y
    span = float(np.hypot(dx, dy))
    if span < 1e-6:
        return None
    ux, uy = dx / span, dy / span
    tol = 1.5
    if (abs(y - 0.0) <= tol or abs(y - T) <= tol) and uy > 0.85:
        return ("wall-front", x)
    if (abs(y - W) <= tol or abs(y - (W - T)) <= tol) and uy < -0.85:
        return ("wall-back", x)
    if (abs(x - 0.0) <= tol or abs(x - T) <= tol) and ux > 0.85:
        return ("wall-left", y)
    if (abs(x - L) <= tol or abs(x - (L - T)) <= tol) and ux < -0.85:
        return ("wall-right", y)
    return None


def _loose_wall_hit(
    x: float,
    y: float,
    params: InsertParams,
) -> Tuple[str, float] | None:
    """End is close to a wall but not square — keep a single slot."""
    L, W, T = params.outer_length, params.outer_width, params.thickness
    tol = T + 1.0
    if abs(y - 0.0) < tol or abs(y - T) < tol:
        return ("wall-front", x)
    if abs(y - W) < tol or abs(y - (W - T)) < tol:
        return ("wall-back", x)
    if abs(x - 0.0) < tol or abs(x - T) < tol:
        return ("wall-left", y)
    if abs(x - L) < tol or abs(x - (L - T)) < tol:
        return ("wall-right", y)
    return None


def _append_unique(outline: Poly, pts: Poly) -> None:
    for p in pts:
        if not outline or abs(p[0] - outline[-1][0]) > 1e-9 or abs(p[1] - outline[-1][1]) > 1e-9:
            outline.append(p)


def _clip_span_to_end(pts: Poly, end_x: float, body_positive: bool) -> Poly:
    """Drop the part of an edge that an angled end has cut away.

    `body_positive` means the plate continues toward increasing x.
    """
    if body_positive:
        return [p for p in pts if p[0] >= end_x - 1e-6]
    return [p for p in pts if p[0] <= end_x + 1e-6]


def _attach_angled_ends(
    bottom: Poly, top: Poly, left: Poly | None, right: Poly | None
) -> Tuple[Poly, Poly]:
    """Join the top and bottom to angled ends, without keeping the uncut corner."""
    if left:
        bottom = [left[0]] + _clip_span_to_end(bottom, left[0][0], True)
        top = _clip_span_to_end(top, left[-1][0], True) + [left[-1]]
    if right:
        bottom = _clip_span_to_end(bottom, right[0][0], False) + [right[0]]
        top = [right[-1]] + _clip_span_to_end(top, right[-1][0], False)
    return bottom, top


def _notched_profile(
    length: float,
    finger_spans: List[Tuple[float, float]],
    notch_spans: List[Tuple[float, ...]],
    finger_y: float,
    gap_y: float,
    notch_y: float,
) -> Poly:
    """Left-to-right edge. Notches win over fingers.

    A notch span may carry its own reach as a third value. Otherwise every notch
    uses `notch_y`.
    """
    cuts = [0.0, length]
    for span in list(finger_spans) + list(notch_spans):
        a, b = span[0], span[1]
        cuts.append(min(length, max(0.0, a)))
        cuts.append(min(length, max(0.0, b)))
    xs = sorted(cuts)
    uniq = [xs[0]]
    for x in xs[1:]:
        if x - uniq[-1] > 1e-6:
            uniq.append(x)
    pts: Poly = []

    def add(x: float, y: float) -> None:
        if not pts or abs(pts[-1][0] - x) > 1e-9 or abs(pts[-1][1] - y) > 1e-9:
            pts.append((x, y))

    def reach_at(mid: float) -> float | None:
        for span in notch_spans:
            if span[0] - 1e-6 <= mid <= span[1] + 1e-6:
                return span[2] if len(span) > 2 else notch_y
        return None

    for i in range(len(uniq) - 1):
        a, b = uniq[i], uniq[i + 1]
        mid = (a + b) / 2.0
        reached = reach_at(mid)
        if reached is not None:
            y = reached
        elif any(s0 - 1e-6 <= mid <= s1 + 1e-6 for s0, s1 in finger_spans):
            y = finger_y
        else:
            y = gap_y
        add(a, y)
        add(b, y)
    return pts


def _vertical_fingers(
    x: float,
    y_lo: float,
    y_hi: float,
    thickness: float,
    pitch: float,
    outward: float,
) -> Poly:
    """Upward edge. `outward` is +1 for a right edge and -1 for a left edge."""
    spans = [(a + y_lo, b + y_lo) for a, b in _spans_for_length(y_hi - y_lo, pitch)]
    pts: Poly = []

    def add(px: float, py: float) -> None:
        if not pts or abs(pts[-1][0] - px) > 1e-9 or abs(pts[-1][1] - py) > 1e-9:
            pts.append((px, py))

    y = y_lo
    add(x, y_lo)
    for a, b in spans:
        if a > y + 1e-9:
            add(x, y)
            add(x, a)
        fx = x + outward * thickness
        add(fx, a)
        add(fx, b)
        add(x, b)
        y = b
    if y < y_hi - 1e-9:
        add(x, y)
        add(x, y_hi)
    else:
        add(x, y_hi)
    return pts


def _side_edge(
    x: float,
    y0: float,
    y1: float,
    finger_span: Tuple[float, float] | None,
    thickness: float,
    pitch: float,
    outward: float,
    floor_contact: bool,
) -> Poly:
    """Vertical edge, bottom to top. A missing span is a straight cut."""
    if finger_span is None:
        return [(x, y0), (x, y1)]
    fy0 = max(finger_span[0], y0)
    fy1 = min(finger_span[1], y1)
    if fy1 < fy0 + 1.0:
        return [(x, y0), (x, y1)]
    pts: Poly = []
    if not floor_contact and fy0 > y0 + 1e-6:
        pts.extend([(x, y0), (x, fy0)])
    run = _vertical_fingers(x, fy0, fy1, thickness, pitch, outward)
    if pts and run and abs(run[0][0] - pts[-1][0]) < 1e-9 and abs(run[0][1] - pts[-1][1]) < 1e-9:
        pts.extend(run[1:])
    else:
        pts.extend(run)
    if fy1 < y1 - 1e-6:
        if not pts or abs(pts[-1][1] - fy1) > 1e-9 or abs(pts[-1][0] - x) > 1e-9:
            pts.append((x, fy1))
        pts.append((x, y1))
    return pts


def _divider_outline(
    length: float,
    y0: float,
    y1: float,
    thickness: float,
    finger_count: int,
    full_height: float,
    floor: bool,
    left_span: Tuple[float, float] | None,
    right_span: Tuple[float, float] | None,
    bottom_notches: List[Tuple[float, float, float]] | None = None,
    top_notches: List[Tuple[float, float, float]] | None = None,
    finger_x0: float | None = None,
    finger_x1: float | None = None,
    left_edge: Poly | None = None,
    right_edge: Poly | None = None,
    left_reach: float | None = None,
    right_reach: float | None = None,
    closed: bool = False,
) -> Poly:
    """Divider plate. Y stays in wall coordinates, so a raised plate starts above 0.

    Bottom fingers pass through the floor only when the plate starts at y=0. Top fingers
    pass through a closed lid only when the plate reaches the wall top. End fingers
    run along `left_span` and `right_span`. Cross-lap notches open to the reach Y carried
    on each notch. `left_edge` and `right_edge`, when set, replace those ends; they run
    bottom to top.
    """
    end_count = _odd_count(finger_count)
    bottom_notches = bottom_notches or []
    top_notches = top_notches or []
    floor_top = thickness if floor else 0.0
    floor_contact = floor and y0 <= 1e-6
    top_contact = closed and y1 >= full_height - 1e-6
    bottom_pitch = full_height / end_count
    end_pitch = (full_height - floor_top) / end_count
    fx0 = 0.0 if finger_x0 is None else max(0.0, finger_x0)
    fx1 = length if finger_x1 is None else min(length, finger_x1)
    along_spans = (
        [(a + fx0, b + fx0) for a, b in _spans_for_length(fx1 - fx0, bottom_pitch)]
        if fx1 > fx0 + 1.0
        else []
    )
    finger_spans = along_spans if floor_contact else []
    top_finger_spans = along_spans if top_contact else []
    if bottom_notches or (floor_contact and finger_x0 is not None):
        bottom = _notched_profile(
            length,
            finger_spans,
            bottom_notches,
            0.0,
            thickness if floor_contact else y0,
            y0,
        )
    elif floor_contact:
        bottom = _bottom_polyline(length, thickness, finger_spans)
    else:
        bottom = [(0.0, y0), (length, y0)]

    right_out = thickness if right_reach is None else right_reach
    left_out = thickness if left_reach is None else left_reach
    right = (
        right_edge
        if right_edge is not None
        else _side_edge(length, y0, y1, right_span, right_out, end_pitch, 1.0, floor_contact)
    )
    if top_notches or top_contact:
        top = list(reversed(_notched_profile(
            length,
            top_finger_spans,
            top_notches,
            full_height if top_contact else y1,
            full_height - thickness if top_contact else y1,
            y1,
        )))
    else:
        top = [(length, y1), (0.0, y1)]
    left_up = (
        left_edge
        if left_edge is not None
        else _side_edge(0.0, y0, y1, left_span, left_out, end_pitch, -1.0, floor_contact)
    )
    left = list(reversed(left_up))
    if left_edge or right_edge:
        bottom, top = _attach_angled_ends(
            bottom,
            top,
            left_up if left_edge else None,
            right if right_edge else None,
        )

    outline: Poly = []
    _append_unique(outline, bottom)
    _append_unique(outline, right)
    _append_unique(outline, top)
    _append_unique(outline, left)
    return outline


def _axis_rect(poly: Poly) -> Tuple[float, float, float, float] | None:
    """Bounding box of an axis-aligned rectangle, or None."""
    pts: Poly = []
    for x, y in poly:
        if pts and abs(x - pts[-1][0]) <= 1e-6 and abs(y - pts[-1][1]) <= 1e-6:
            continue
        pts.append((x, y))
    if len(pts) >= 2 and abs(pts[0][0] - pts[-1][0]) <= 1e-6 and abs(pts[0][1] - pts[-1][1]) <= 1e-6:
        pts = pts[:-1]
    if len(pts) != 4:
        return None
    for i in range(4):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % 4]
        if abs(ax - bx) > 1e-6 and abs(ay - by) > 1e-6:
            return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x1 - x0 < 0.2 or y1 - y0 < 0.2:
        return None
    return (x0, y0, x1, y1)


def _shoelace(poly: Poly) -> float:
    area = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return area / 2.0


def _on_segment(x: float, y: float, a: Vec2, b: Vec2, eps: float = 1e-6) -> bool:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    span = math.hypot(dx, dy)
    if span < 1e-12:
        return math.hypot(x - ax, y - ay) <= eps
    if abs((x - ax) * dy - (y - ay) * dx) > eps * span:
        return False
    dot = (x - ax) * dx + (y - ay) * dy
    return -eps * span <= dot <= span * span + eps * span


def _strictly_inside(x: float, y: float, poly: Poly) -> bool:
    """True when (x, y) is in the interior. Boundary points are outside."""
    pts = list(poly)
    if len(pts) >= 2 and abs(pts[0][0] - pts[-1][0]) <= 1e-9 and abs(pts[0][1] - pts[-1][1]) <= 1e-9:
        pts = pts[:-1]
    if len(pts) < 3:
        return False
    n = len(pts)
    for i in range(n):
        if _on_segment(x, y, pts[i], pts[(i + 1) % n]):
            return False
    return _point_in_poly(x, y, pts)


def _open_slots_into_outline(
    outline: Poly, holes: List[Poly], kerf: float
) -> Tuple[Poly, List[Poly]]:
    """Join holes that meet the outline so they become one opening.

    A finger that starts on an edge notch, or a tab slot that runs out through
    an edge, shares that line with the outline. Drawn as its own path, the laser
    traces the shared line and the slot stays a separate cut. The slot is cut
    out of the outline instead. Holes that do not reach an edge stay holes.
    """
    tol = max(kerf * 0.5 + 0.05, 0.05)
    current = list(outline)
    kept: List[Poly] = []
    for hole in holes:
        rect = _axis_rect(hole)
        opened = (
            _cut_rect_from_outline(current, rect, tol)
            if rect is not None
            else _cut_poly_from_outline(current, hole)
        )
        if opened is None:
            kept.append(hole)
        else:
            current = opened
    return current, kept


def _cut_rect_from_outline(
    outline: Poly, rect: Tuple[float, float, float, float], tol: float
) -> Poly | None:
    """Return the outline with `rect` opened through any edge it touches."""
    outline = _as_ccw(outline)
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    if not _point_in_poly(cx, cy, outline):
        return None
    grown = _grow_rect_to_edges(rect, outline, tol)
    if grown == rect and not _rect_crosses_outline(rect, outline):
        return None
    segments = _outline_minus_rect(outline, grown)
    if not segments:
        return None
    loops = _stitch_loops(segments)
    if len(loops) != 1:
        return None
    loop = loops[0]
    if _shoelace(loop) < 0.0:
        loop = list(reversed(loop))
    old_area = abs(_shoelace(outline))
    new_area = abs(_shoelace(loop))
    if not (old_area * 0.5 < new_area < old_area - 0.5):
        return None
    if _strictly_inside(cx, cy, loop):
        return None
    return loop


def _as_ccw(poly: Poly) -> Poly:
    pts = _ring(poly)
    if len(pts) >= 3 and _shoelace(pts) < 0.0:
        pts = list(reversed(pts))
    return pts


def _cut_poly_from_outline(outline: Poly, hole: Poly) -> Poly | None:
    """Open a non-rectangular hole that crosses the outline, such as a slide slot."""
    outline = _as_ccw(outline)
    ccw = _as_ccw(hole)
    if len(ccw) < 3 or not _poly_hits_outline(ccw, outline):
        return None
    sample = _interior_sample(ccw, outline)
    if sample is None:
        return None
    segments = _outline_minus_poly(outline, ccw)
    if not segments:
        return None
    loops = _stitch_loops(segments)
    if len(loops) != 1:
        return None
    loop = loops[0]
    if _shoelace(loop) < 0.0:
        loop = list(reversed(loop))
    old_area = abs(_shoelace(outline))
    new_area = abs(_shoelace(loop))
    if not (old_area * 0.5 < new_area < old_area - 0.5):
        return None
    if _strictly_inside(sample[0], sample[1], loop):
        return None
    return loop


def _poly_hits_outline(hole: Poly, outline: Poly) -> bool:
    other = _ring(outline)
    n = len(other)
    if n < 3:
        return False
    pts = _ring(hole)
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        for j in range(n):
            if _segment_t(a, b, other[j], other[(j + 1) % n]) is not None:
                return True
    return False


def _interior_sample(hole: Poly, outline: Poly) -> Vec2 | None:
    """A point that is inside both the hole and the outline."""
    pts = _ring(hole)
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    if _strictly_inside(cx, cy, hole) and _strictly_inside(cx, cy, outline):
        return (cx, cy)
    for i in range(len(pts)):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % len(pts)]
        mx = (ax + bx) / 2.0 * 0.65 + cx * 0.35
        my = (ay + by) / 2.0 * 0.65 + cy * 0.35
        if _strictly_inside(mx, my, hole) and _strictly_inside(mx, my, outline):
            return (mx, my)
    return None


def _outline_minus_poly(outline: Poly, hole: Poly) -> List[Tuple[Vec2, Vec2]]:
    """Directed edges of (inside outline) minus (inside hole). `hole` is counterclockwise."""
    segments: List[Tuple[Vec2, Vec2]] = []
    pts = _ring(outline)
    n = len(pts)
    for i in range(n):
        segments.extend(_outside_poly(pts[i], pts[(i + 1) % n], hole))
    # Clockwise, so the left side is outside the hole.
    m = len(hole)
    for i in range(m):
        segments.extend(_inside_outline(hole[(i + 1) % m], hole[i], outline))
    return segments


def _outside_poly(a: Vec2, b: Vec2, hole: Poly) -> List[Tuple[Vec2, Vec2]]:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    ts = [0.0, 1.0]
    hpts = _ring(hole)
    m = len(hpts)
    for i in range(m):
        hit = _segment_t(a, b, hpts[i], hpts[(i + 1) % m])
        if hit is not None:
            ts.append(hit)
    kept: List[Tuple[Vec2, Vec2]] = []
    ordered = sorted(set(round(t, 8) for t in ts))
    for t0, t1 in zip(ordered, ordered[1:]):
        if t1 - t0 < 1e-8:
            continue
        tm = (t0 + t1) / 2.0
        mx, my = ax + dx * tm, ay + dy * tm
        if _covered_by_hole(mx, my, dx, dy, hole):
            continue
        kept.append(((ax + dx * t0, ay + dy * t0), (ax + dx * t1, ay + dy * t1)))
    return kept


def _covered_by_hole(x: float, y: float, dx: float, dy: float, hole: Poly) -> bool:
    if _strictly_inside(x, y, hole):
        return True
    pts = _ring(hole)
    if not any(_on_segment(x, y, pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))):
        return False
    span = math.hypot(dx, dy) or 1.0
    # The hole claims the edge only when its interior is on the material side.
    return _point_in_poly(x - dy / span * 0.04, y + dx / span * 0.04, hole)


def _grow_rect_to_edges(
    rect: Tuple[float, float, float, float], outline: Poly, tol: float
) -> Tuple[float, float, float, float]:
    """Push each side that sits on an outline edge just past that edge.

    Kerf leaves the slot a fraction of a millimetre short of the notch, so the
    two cuts do not quite meet. Growing across that gap lets them become one
    opening without moving the other three sides.
    """
    x0, y0, x1, y1 = rect
    rcx, rcy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    nx0, ny0, nx1, ny1 = x0, y0, x1, y1
    pts = _ring(outline)
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        if math.hypot(dx, dy) < 1e-9:
            continue
        # The slot has to sit in the material, on the left of the outline edge.
        if dx * (rcy - ay) - dy * (rcx - ax) <= 1e-6:
            continue
        if abs(dy) <= 1e-7:
            ex0, ex1 = (ax, bx) if ax <= bx else (bx, ax)
            if min(x1, ex1) - max(x0, ex0) < 0.3:
                continue
            y = ay
            if abs(y - y0) <= tol:
                ny0 = min(ny0, y - 0.02)
            elif abs(y - y1) <= tol:
                ny1 = max(ny1, y + 0.02)
        elif abs(dx) <= 1e-7:
            ey0, ey1 = (ay, by) if ay <= by else (by, ay)
            if min(y1, ey1) - max(y0, ey0) < 0.3:
                continue
            x = ax
            if abs(x - x0) <= tol:
                nx0 = min(nx0, x - 0.02)
            elif abs(x - x1) <= tol:
                nx1 = max(nx1, x + 0.02)
    if nx1 - nx0 < 0.2 or ny1 - ny0 < 0.2:
        return rect
    return (nx0, ny0, nx1, ny1)


def _ring(poly: Poly) -> Poly:
    pts = list(poly)
    if len(pts) >= 2 and abs(pts[0][0] - pts[-1][0]) <= 1e-9 and abs(pts[0][1] - pts[-1][1]) <= 1e-9:
        pts = pts[:-1]
    return pts


def _rect_crosses_outline(rect: Tuple[float, float, float, float], outline: Poly) -> bool:
    x0, y0, x1, y1 = rect
    pts = _ring(outline)
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        if _segment_hits_rect(ax, ay, bx, by, x0, y0, x1, y1):
            return True
    return False


def _segment_hits_rect(
    ax: float, ay: float, bx: float, by: float,
    x0: float, y0: float, x1: float, y1: float,
) -> bool:
    if (x0 <= ax <= x1 and y0 <= ay <= y1) or (x0 <= bx <= x1 and y0 <= by <= y1):
        return True
    ts = _rect_split_ts(ax, ay, bx, by, (x0, y0, x1, y1))
    return any(1e-6 < t < 1.0 - 1e-6 for t in ts)


def _rect_split_ts(
    ax: float, ay: float, bx: float, by: float, rect: Tuple[float, float, float, float]
) -> List[float]:
    dx, dy = bx - ax, by - ay
    x0, y0, x1, y1 = rect
    ts = [0.0, 1.0]
    for val, origin, delta, lo, hi, horizontal in (
        (x0, ax, dx, y0, y1, False),
        (x1, ax, dx, y0, y1, False),
        (y0, ay, dy, x0, x1, True),
        (y1, ay, dy, x0, x1, True),
    ):
        if abs(delta) < 1e-12:
            continue
        t = (val - origin) / delta
        if t < -1e-8 or t > 1.0 + 1e-8:
            continue
        if horizontal:
            cross = ax + dx * t
        else:
            cross = ay + dy * t
        if lo - 1e-6 <= cross <= hi + 1e-6:
            ts.append(min(1.0, max(0.0, t)))
    return ts


def _outline_minus_rect(
    outline: Poly, rect: Tuple[float, float, float, float]
) -> List[Tuple[Vec2, Vec2]]:
    """Directed edges of (inside outline) minus (inside rect). Interior stays on the left."""
    x0, y0, x1, y1 = rect
    segments: List[Tuple[Vec2, Vec2]] = []
    pts = _ring(outline)
    n = len(pts)
    for i in range(n):
        segments.extend(_outside_rect(pts[i], pts[(i + 1) % n], rect))
    # Rectangle walked clockwise, so the left side is outside the hole.
    rect_edges = (
        ((x0, y0), (x0, y1)),
        ((x0, y1), (x1, y1)),
        ((x1, y1), (x1, y0)),
        ((x1, y0), (x0, y0)),
    )
    for a, b in rect_edges:
        segments.extend(_inside_outline(a, b, outline))
    return segments


def _outside_rect(
    a: Vec2, b: Vec2, rect: Tuple[float, float, float, float]
) -> List[Tuple[Vec2, Vec2]]:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    ts = _rect_split_ts(ax, ay, bx, by, rect)
    kept: List[Tuple[Vec2, Vec2]] = []
    ordered = sorted(set(ts))
    rx0, ry0, rx1, ry1 = rect
    rcx, rcy = (rx0 + rx1) / 2.0, (ry0 + ry1) / 2.0
    for t0, t1 in zip(ordered, ordered[1:]):
        if t1 - t0 < 1e-8:
            continue
        tm = (t0 + t1) / 2.0
        mx, my = ax + dx * tm, ay + dy * tm
        inside = rx0 < mx < rx1 and ry0 < my < ry1
        on_boundary = (
            rx0 - 1e-6 <= mx <= rx1 + 1e-6
            and ry0 - 1e-6 <= my <= ry1 + 1e-6
            and (abs(mx - rx0) <= 1e-6 or abs(mx - rx1) <= 1e-6 or abs(my - ry0) <= 1e-6 or abs(my - ry1) <= 1e-6)
        )
        # A shared edge is the line the two cuts would trace twice. Drop it.
        rect_on_left = dx * (rcy - ay) - dy * (rcx - ax) > 0.0
        if inside or (on_boundary and rect_on_left):
            continue
        kept.append(((ax + dx * t0, ay + dy * t0), (ax + dx * t1, ay + dy * t1)))
    return kept


def _inside_outline(a: Vec2, b: Vec2, outline: Poly) -> List[Tuple[Vec2, Vec2]]:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    ts = [0.0, 1.0]
    pts = _ring(outline)
    n = len(pts)
    for i in range(n):
        hit = _segment_t(a, b, pts[i], pts[(i + 1) % n])
        if hit is not None:
            ts.append(hit)
    kept: List[Tuple[Vec2, Vec2]] = []
    for t0, t1 in zip(sorted(set(ts)), sorted(set(ts))[1:]):
        if t1 - t0 < 1e-8:
            continue
        tm = (t0 + t1) / 2.0
        mx, my = ax + dx * tm, ay + dy * tm
        if _strictly_inside(mx, my, outline):
            kept.append(((ax + dx * t0, ay + dy * t0), (ax + dx * t1, ay + dy * t1)))
    return kept


def _segment_t(a: Vec2, b: Vec2, c: Vec2, d: Vec2) -> float | None:
    ax, ay = a
    bx, by = b
    cx, cy = c
    dx, dy = d
    rx, ry = bx - ax, by - ay
    sx, sy = dx - cx, dy - cy
    den = rx * sy - ry * sx
    if abs(den) < 1e-12:
        return None
    qpx, qpy = cx - ax, cy - ay
    t = (qpx * sy - qpy * sx) / den
    u = (qpx * ry - qpy * rx) / den
    if -1e-8 <= t <= 1.0 + 1e-8 and -1e-8 <= u <= 1.0 + 1e-8:
        return min(1.0, max(0.0, t))
    return None


def _snap_pt(p: Vec2) -> Vec2:
    return (round(p[0], 5), round(p[1], 5))


def _stitch_loops(segments: List[Tuple[Vec2, Vec2]]) -> List[Poly]:
    """Walk directed edges into closed loops. At a junction, take the next left turn."""
    outgoing: dict[Vec2, List[Vec2]] = {}
    indeg: dict[Vec2, int] = {}
    for a, b in segments:
        a, b = _snap_pt(a), _snap_pt(b)
        if abs(a[0] - b[0]) <= 1e-9 and abs(a[1] - b[1]) <= 1e-9:
            continue
        outgoing.setdefault(a, []).append(b)
        indeg[b] = indeg.get(b, 0) + 1
        indeg.setdefault(a, indeg.get(a, 0))
    nodes = set(outgoing) | set(indeg)
    for node in nodes:
        if len(outgoing.get(node, [])) != indeg.get(node, 0):
            return []
    remaining = {node: list(dests) for node, dests in outgoing.items()}

    def pick(prev: Vec2, here: Vec2, options: List[Vec2]) -> Vec2:
        incoming = math.atan2(here[1] - prev[1], here[0] - prev[0])

        def turn(opt: Vec2) -> float:
            ang = math.atan2(opt[1] - here[1], opt[0] - here[0])
            return (ang - incoming) % (2.0 * math.pi)

        return min(options, key=turn)

    loops: List[Poly] = []
    guard_edges = sum(len(dests) for dests in remaining.values()) + 2
    while any(remaining.values()):
        start = next(node for node, dests in remaining.items() if dests)
        here = start
        prev: Vec2 | None = None
        poly: Poly = [start]
        seen = 0
        while True:
            options = remaining.get(here, [])
            if not options:
                return []
            nxt = options[0] if prev is None else pick(prev, here, options)
            options.remove(nxt)
            prev, here = here, nxt
            seen += 1
            if seen > guard_edges:
                return []
            if here == start:
                break
            poly.append(here)
        if len(poly) >= 3 and abs(_shoelace(poly)) > 1.0:
            loops.append(poly)
    return loops


def build_panels(params: InsertParams) -> List[Panel]:
    """Nest laser panels with spacing."""
    L, W, H, T = params.outer_length, params.outer_width, params.height, params.thickness
    fingers = params.finger_count
    gap = 4.0
    panels: List[Panel] = []
    x_cursor = 0.0
    y_row = 0.0
    row_h = 0.0

    def place(
        name: str,
        outline: Poly,
        holes: List[Poly],
        w: float,
        h: float,
        label: str = "",
    ) -> None:
        nonlocal x_cursor, y_row, row_h
        # Simple left-to-right, wrap if needed (fixed sheet width ~600 mm for nest preview)
        sheet_w = 600.0
        if x_cursor > 0 and x_cursor + w > sheet_w:
            x_cursor = 0.0
            y_row += row_h + gap
            row_h = 0.0
        panels.append(
            Panel(
                name=name,
                outline=outline,
                holes=holes,
                origin=(x_cursor, y_row),
                label=label,
            )
        )
        x_cursor += w + gap
        row_h = max(row_h, h)

    # Floor fingers match the wall bottoms. A closed lid uses the same joint at the top.
    # Long walls own the corners.
    pitch = H / _odd_count(fingers)
    closed = params.closed_top()
    edge_joints = params.floor or closed
    length_spans = _floor_joint_spans(L, T, pitch, owns_corners=True) if edge_joints else []
    width_spans = _floor_joint_spans(W, T, pitch, owns_corners=False) if edge_joints else []
    div_joints = _divider_joints(params)

    def divider_slots(d: Divider, joints: List[_DivJoint], kind: str, y_open: float) -> List[Poly]:
        if d.leans():
            return _leaned_floor_slots(d, params, joints, notch_kind=kind, y_open=y_open)
        return _divider_finger_slots_on_floor(d, params, joints, notch_kind=kind, y_open=y_open)

    if params.floor:
        floor_outline = _offset_kerf(
            _floor_outline(L, W, T, length_spans, width_spans), params.kerf, outward=True
        )
        floor_holes: List[Poly] = []
        for d, joints in zip(params.dividers, div_joints):
            # A divider that rests on the floor without fingers starts above this
            # panel, so the floor stays solid under it.
            plate = d.plate_span(H, T, True, closed)
            if plate is not None and plate[0] <= 1e-6:
                floor_holes.extend(divider_slots(d, joints, "cross-bottom", 0.0))
        place("floor", floor_outline, floor_holes, L, W)

    if closed:
        lid_outline = _offset_kerf(
            _floor_outline(L, W, T, length_spans, width_spans), params.kerf, outward=True
        )
        lid_holes: List[Poly] = []
        for d, joints in zip(params.dividers, div_joints):
            plate = d.plate_span(H, T, params.floor, True)
            if plate is not None and plate[1] >= H - 1e-6:
                lid_holes.extend(divider_slots(d, joints, "cross-top", H))
        place("lid-closed", lid_outline, lid_holes, L, W, "Lid")

    # Four walls: long, long, short, short
    # Front/back: length L, fingers on short ends; left/right: length W
    for name, length, left_male, right_male, floor_spans in [
        ("wall-front", L, True, True, length_spans),
        ("wall-back", L, False, False, length_spans),
        ("wall-left", W, True, False, width_spans),
        ("wall-right", W, False, True, width_spans),
    ]:
        wall_h = params.wall_height(name)
        outline = _wall_panel_outline(
            length,
            wall_h,
            T,
            fingers,
            left_male,
            right_male,
            floor_spans if params.floor else None,
            left_joint=params.wall_joint(name, True),
            right_joint=params.wall_joint(name, False),
            top_fingers=floor_spans if closed else None,
        )
        outline = _offset_kerf(outline, params.kerf, outward=True)
        holes: List[Poly] = []
        for d in params.dividers:
            holes.extend(_divider_end_slots_for_wall(name, length, H, T, d, params))
        holes.extend(_slide_slot_holes(params, name))
        holes.extend(_latch_wall_holes(params, name))
        # A finger or a lid slot that meets the wall edge becomes part of that edge.
        outline, holes = _open_slots_into_outline(outline, holes, params.kerf)
        place(name, outline, holes, length + 2 * T, wall_h + T)

    floor_top = T if params.floor else 0.0
    end_pitch = (H - floor_top) / _odd_count(fingers)
    for i, d in enumerate(params.dividers):
        plate = d.plate_span(H, T, params.floor, closed)
        if plate is None:
            continue
        y0, y1 = plate
        span = _divider_length(d)
        joints = div_joints[i]
        if d.leans():
            outline, holes = _leaned_divider_plate(d, params, joints, y0, y1)
            outline = _offset_kerf(outline, params.kerf, outward=True)
            outline, holes = _open_slots_into_outline(outline, holes, params.kerf)
            xs = [p[0] for p in outline]
            ys = [p[1] for p in outline]
            minx, miny = min(xs), min(ys)
            outline = [(p[0] - minx, p[1] - miny) for p in outline]
            holes = [[(p[0] - minx, p[1] - miny) for p in hole] for hole in holes]
            place(
                f"divider-{i}",
                outline,
                holes,
                max(xs) - minx,
                max(ys) - miny,
                d.label,
            )
            continue
        lid_base = H - T if closed else y1
        own_fingers = (max(y0, floor_top), min(y1, lid_base))

        def end_span(at_start: bool, hits_wall: bool) -> Tuple[float, float] | None:
            if hits_wall:
                return own_fingers
            for joint in joints:
                if joint.kind == "stub" and joint.square and joint.at_start == at_start:
                    return (joint.y0, joint.y1)
            return None

        def end_reach(at_start: bool) -> float:
            for joint in joints:
                if joint.kind == "stub" and joint.at_start == at_start and joint.half:
                    return T / 2.0
            return T

        left_span = end_span(
            True, _square_wall_hit(d.x1, d.y1, d.x2, d.y2, params) is not None
        )
        right_span = end_span(
            False, _square_wall_hit(d.x2, d.y2, d.x1, d.y1, params) is not None
        )
        left_inset, right_inset = _end_insets(span, joints, T)
        body = span - left_inset - right_inset
        bottom_notches = _body_notches(
            joints, "cross-bottom", params.kerf, left_inset, body, y0, y1
        )
        top_notches = _body_notches(
            joints, "cross-top", params.kerf, left_inset, body, y0, y1
        )
        mate_left = _angled_stub_edge(joints, True, 0.0, -1.0, y0, y1, T, end_pitch, lambda z: z, 1.0, y0, y1)
        mate_right = _angled_stub_edge(joints, False, body, 1.0, y0, y1, T, end_pitch, lambda z: z, 1.0, y0, y1)
        if mate_left is not None:
            left_span = None
        if mate_right is not None:
            right_span = None
        fx0 = fx1 = None
        if mate_left is not None or mate_right is not None:
            lim0, lim1 = _floor_finger_limits(span, joints, T)
            fx0 = lim0 - left_inset
            fx1 = lim1 - left_inset
        outline = _divider_outline(
            body,
            y0,
            y1,
            T,
            fingers,
            H,
            params.floor,
            left_span,
            right_span,
            bottom_notches,
            top_notches,
            fx0,
            fx1,
            mate_left,
            mate_right,
            end_reach(True),
            end_reach(False),
            closed,
        )
        holes = _tee_holes(joints, left_inset, body, H, T, params.kerf, end_pitch, params.floor)
        holes.extend(_closed_cross_holes(joints, left_inset, body, y0, y1, params.kerf))
        holes.extend(_lean_slot_holes(joints, left_inset, body, y0, 1.0, params.kerf))
        holes.extend(_lean_finger_holes(joints, left_inset, lambda z: z, 1.0, end_pitch, T, params.kerf))
        outline = _offset_kerf(outline, params.kerf, outward=True)
        outline, holes = _open_slots_into_outline(outline, holes, params.kerf)
        xs = [p[0] for p in outline]
        ys = [p[1] for p in outline]
        minx, miny = min(xs), min(ys)
        outline = [(p[0] - minx, p[1] - miny) for p in outline]
        holes = [[(p[0] - minx, p[1] - miny) for p in hole] for hole in holes]
        place(
            f"divider-{i}",
            outline,
            holes,
            max(xs) - minx,
            max(ys) - miny,
            d.label,
        )

    _add_lid_panels(params, place)
    return panels


def _finger_slots_between(
    along: float,
    wall_length: float,
    thickness: float,
    kerf: float,
    y_lo: float,
    y_hi: float,
    pitch: float,
    y_min: float = 0.0,
) -> List[Poly]:
    """Finger slots from y_lo to y_hi. y_min keeps them out of a floor joint."""
    sw = thickness + kerf
    sx = min(max(0.0, along - sw / 2.0), max(0.0, wall_length - sw))
    lo = max(y_lo, y_min)
    hi = y_hi
    if hi < lo + 1.0 or pitch <= 1e-6:
        return []
    holes: List[Poly] = []
    for a, b in _spans_for_length(hi - lo, pitch):
        yy0 = a + lo - kerf / 2.0
        yy1 = b + lo + kerf / 2.0
        if y_min > 0.0:
            yy0 = max(y_min, yy0)
        yy0 = max(0.0, yy0)
        yy1 = min(y_hi, yy1)
        if yy1 > yy0:
            holes.append(_rect(sx, yy0, sw, yy1 - yy0))
    return holes


def _plain_slot_in_wall(
    along: float,
    wall_length: float,
    wall_height: float,
    thickness: float,
    kerf: float,
    y_lo: float | None = None,
    y_hi: float | None = None,
) -> Poly:
    """One slot for an angled end that does not take a square finger joint."""
    sw = thickness + kerf
    sx = min(max(0.0, along - sw / 2.0), max(0.0, wall_length - sw))
    full = y_lo is None or (y_lo <= 1e-6 and (y_hi is None or y_hi >= wall_height - 1e-6))
    if full:
        return _rect(sx, thickness * 0.5, sw, max(wall_height - thickness - 2.0, 1.0))
    lo = max(0.0, (y_lo or 0.0) + 1.0)
    hi = min(wall_height, (y_hi if y_hi is not None else wall_height) - 1.0)
    return _rect(sx, lo, sw, max(hi - lo, 1.0))


def _clip_along(
    a0: float, z0: float, a1: float, z1: float, lo: float, hi: float
) -> Tuple[float, float, float, float] | None:
    """Clip a segment to the along-coordinate interval [lo, hi]."""
    da = a1 - a0
    if abs(da) < 1e-9:
        if lo <= a0 <= hi:
            return a0, z0, a1, z1
        return None
    ts = [0.0, 1.0]
    for edge in (lo, hi):
        t = (edge - a0) / da
        if 0.0 <= t <= 1.0:
            ts.append(t)
    ts = sorted(ts)
    for i in range(len(ts) - 1):
        tm = (ts[i] + ts[i + 1]) / 2.0
        am = a0 + da * tm
        if lo - 1e-6 <= am <= hi + 1e-6:
            t0, t1 = ts[i], ts[i + 1]

            def at(t: float) -> Tuple[float, float]:
                return a0 + (a1 - a0) * t, z0 + (z1 - z0) * t

            p0, q0 = at(t0)
            p1, q1 = at(t1)
            if math.hypot(p1 - p0, q1 - q0) < 1.0:
                return None
            return p0, q0, p1, q1
    return None


def _slanted_slot(a0: float, z0: float, a1: float, z1: float, half: float) -> Poly:
    """Rectangle of half-width `half` around a slanted centerline, in wall coordinates."""
    dx, dz = a1 - a0, z1 - z0
    norm = math.hypot(dx, dz)
    if norm < 1e-6:
        return _rect(a0 - half, min(z0, z1), half * 2.0, abs(z1 - z0))
    px, pz = -dz / norm, dx / norm
    return [
        (a0 + px * half, z0 + pz * half),
        (a1 + px * half, z1 + pz * half),
        (a1 - px * half, z1 - pz * half),
        (a0 - px * half, z0 - pz * half),
    ]


def _joint_rate(slope: float, y_per_z: float) -> Tuple[float, float, float]:
    """Unit tangent (tx, ty) and its length per world-height, in a flat pattern."""
    rate = math.hypot(slope, y_per_z)
    rate = max(rate, 1e-6)
    return slope / rate, y_per_z / rate, rate


def _clip_polyline_band(pts: Poly, lo: float, hi: float) -> Poly:
    """Clip an open polyline so every point has y in [lo, hi]."""
    if len(pts) < 2 or hi < lo:
        return pts

    def clip_seg(a: Vec2, b: Vec2) -> Tuple[Vec2, Vec2] | None:
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        u0, u1 = 0.0, 1.0
        for p, q in ((-dy, ay - lo), (dy, hi - ay)):
            if abs(p) < 1e-12:
                if q < 0.0:
                    return None
                continue
            t = q / p
            if p < 0.0:
                if t > u1:
                    return None
                u0 = max(u0, t)
            else:
                if t < u0:
                    return None
                u1 = min(u1, t)
        if u1 < u0:
            return None
        return (ax + dx * u0, ay + dy * u0), (ax + dx * u1, ay + dy * u1)

    out: Poly = []
    for i in range(len(pts) - 1):
        seg = clip_seg(pts[i], pts[i + 1])
        if seg is None:
            continue
        for p in seg:
            if not out or abs(out[-1][0] - p[0]) > 1e-6 or abs(out[-1][1] - p[1]) > 1e-6:
                out.append(p)
    return out


def _z_finger_spans(z0: float, z1: float, pitch: float, rate: float) -> List[Tuple[float, float]]:
    """Finger intervals of world height. `rate` is plate distance per world height."""
    if z1 < z0 + 1e-6 or pitch <= 1e-6:
        return []
    edge = (z1 - z0) * rate
    if edge < 1.0:
        return []
    return [(z0 + a / rate, z0 + b / rate) for a, b in _spans_for_length(edge, pitch)]


def _angled_end_edge(
    x_mid: float,
    z0: float,
    z1: float,
    slope: float,
    anchor: float,
    thickness: float,
    finger_z0: float,
    finger_z1: float,
    pitch: float,
    outward: float,
    y_of,
    y_per_z: float,
    y_lo: float,
    y_hi: float,
    reach: float | None = None,
) -> Poly:
    """Bottom-to-top end. Fingers stick out along the normal of the mating face.

    `x_mid` is the mating midplane at `anchor`. Gaps sit on the near face.
    A full tab reaches the far face. A half-depth tab stops on the midplane.
    """
    _tx, _ty, rate = _joint_rate(slope, y_per_z)
    # Perpendicular pointing outward (toward the mating piece).
    nx, ny = -_ty, _tx
    if nx * outward < -1e-9 or (abs(nx) <= 1e-9 and ny * outward < 0.0):
        nx, ny = -nx, -ny
    half = thickness / 2.0
    finger_out = half if reach is None or reach > thickness * 0.75 else 0.0
    fz0 = min(max(finger_z0, z0), z1)
    fz1 = max(min(finger_z1, z1), z0)
    spans = _z_finger_spans(fz0, fz1, pitch, rate)

    def at(z: float, finger: bool) -> Vec2:
        dist = finger_out if finger else -half
        return (
            x_mid + slope * (z - anchor) + nx * dist,
            y_of(z) + ny * dist,
        )

    pts: Poly = []

    def add(z: float, finger: bool) -> None:
        p = at(z, finger)
        if not pts or abs(pts[-1][0] - p[0]) > 1e-9 or abs(pts[-1][1] - p[1]) > 1e-9:
            pts.append(p)

    z = z0
    add(z0, False)
    for a, b in spans:
        a = min(max(a, z0), z1)
        b = min(max(b, z0), z1)
        if b < a + 1e-6:
            continue
        if a > z + 1e-9:
            add(z, False)
            add(a, False)
        add(a, True)
        add(b, True)
        add(b, False)
        z = b
    if z1 > z + 1e-9:
        add(z, False)
        add(z1, False)
    else:
        add(z1, False)
    clipped = _clip_polyline_band(pts, y_lo, y_hi)
    return clipped if len(clipped) >= 2 else pts


def _angled_stub_edge(
    joints: List[_DivJoint],
    at_start: bool,
    x_mid: float,
    outward: float,
    z0: float,
    z1: float,
    thickness: float,
    pitch: float,
    y_of,
    y_per_z: float,
    y_lo: float,
    y_hi: float,
) -> Poly | None:
    """Angled finger end where this divider meets a tilted one, or None."""
    joint = next((j for j in joints if j.kind == "lean-stub" and j.at_start == at_start), None)
    if joint is None:
        return None
    return _angled_end_edge(
        x_mid,
        z0,
        z1,
        joint.slope,
        joint.anchor,
        thickness,
        joint.y0,
        joint.y1,
        pitch,
        outward,
        y_of,
        y_per_z,
        y_lo,
        y_hi,
        thickness / 2.0 if joint.half else thickness,
    )


def _lean_finger_holes(
    joints: List[_DivJoint],
    x_shift: float,
    y_of,
    y_per_z: float,
    pitch: float,
    thickness: float,
    kerf: float,
) -> List[Poly]:
    """Finger slots in a through-piece, square to its face, along the joint line."""
    holes: List[Poly] = []
    half = (thickness + kerf) / 2.0
    for joint in joints:
        if joint.kind != "lean-finger":
            continue
        _tx, ty, rate = _joint_rate(joint.slope, y_per_z)
        px, py = -ty, joint.slope / rate
        spans = _z_finger_spans(joint.y0, joint.y1, pitch, rate)
        for a, b in spans:
            def center(z: float, item: _DivJoint = joint) -> Vec2:
                return (item.t + item.slope * (z - item.anchor) - x_shift, y_of(z))

            c0, c1 = center(a), center(b)
            holes.append(
                [
                    (c0[0] + px * half, c0[1] + py * half),
                    (c1[0] + px * half, c1[1] + py * half),
                    (c1[0] - px * half, c1[1] - py * half),
                    (c0[0] - px * half, c0[1] - py * half),
                ]
            )
    return holes


def _leaned_floor_slots(
    d: Divider,
    params: InsertParams,
    joints: List[_DivJoint],
    notch_kind: str = "cross-bottom",
    y_open: float = 0.0,
) -> List[Poly]:
    """Finger slots for a leaned divider. The sheet crosses the floor at an angle, so each slot is wider."""
    length = _divider_length(d)
    if length < 1e-6:
        return []
    wide = params.thickness / max(0.2, abs(math.cos(d.tilt_radians())))
    t0, t1 = _floor_finger_limits(length, joints, params.thickness)
    pitch = params.height / _odd_count(params.finger_count)
    spans = [(a + t0, b + t0) for a, b in _spans_for_length(max(0.0, t1 - t0), pitch)]
    spans = _subtract_spans(spans, _notch_intervals(joints, notch_kind, params.kerf, y_open=y_open))
    holes: List[Poly] = []
    for a, b in spans:
        if b - a < 1.0:
            continue
        slot = _slot_along_centerline(d, a, b, wide, params.kerf)
        if slot:
            holes.append(slot)
    return holes


def _leaned_wall_slots(
    wall_name: str,
    wall_length: float,
    wall_height: float,
    thickness: float,
    d: Divider,
    params: InsertParams,
) -> List[Poly]:
    """Slots where a leaned divider meets this wall.

    A square end is fingered along the slant. Any other end keeps one slot.
    """
    plate = d.plate_span(params.height, thickness, params.floor, params.closed_top())
    if plate is None:
        return []
    y0, y1 = plate
    floor_top = thickness if params.floor else 0.0
    z0 = max(y0, floor_top)
    z1 = min(y1, wall_height)
    if params.closed_top():
        z1 = min(z1, params.height - params.thickness)
    if z1 < z0 + 1.0:
        return []
    ux, uy, length = _unit_dir(d)
    if length < 1e-6:
        return []
    nx, ny = -uy, ux
    tan_a = math.tan(d.tilt_radians())
    cos_a = max(0.2, abs(math.cos(d.tilt_radians())))
    axis = (1.0, 0.0) if wall_name in ("wall-front", "wall-back") else (0.0, 1.0)
    n_along = nx * axis[0] + ny * axis[1]
    normals = {
        "wall-front": (0.0, -1.0),
        "wall-back": (0.0, 1.0),
        "wall-left": (-1.0, 0.0),
        "wall-right": (1.0, 0.0),
    }
    wn = normals[wall_name]
    sin_hit = max(0.35, abs(ux * wn[0] + uy * wn[1]))
    pitch = (params.height - floor_top) / _odd_count(params.finger_count)
    holes: List[Poly] = []
    for x, y, ox, oy in (
        (d.x1, d.y1, d.x2, d.y2),
        (d.x2, d.y2, d.x1, d.y1),
    ):
        square = _square_wall_hit(x, y, ox, oy, params)
        loose = None if square is not None else _loose_wall_hit(x, y, params)
        hit = square or loose
        if hit is None or hit[0] != wall_name:
            continue
        along = hit[1]

        def wall_segment(za: float, zb: float) -> Poly:
            a0 = along + n_along * (za - y0) * tan_a
            a1 = along + n_along * (zb - y0) * tan_a
            half = (thickness + params.kerf) / 2.0
            if square is None:
                half = (thickness / sin_hit + params.kerf) / 2.0
            clipped = _clip_along(a0, za, a1, zb, 1.0, max(1.0, wall_length - 1.0))
            if clipped is None:
                return []
            slot = _slanted_slot(clipped[0], clipped[1], clipped[2], clipped[3], half)
            # Keep the slot out of the floor joint and inside the wall.
            ring = slot + [slot[0]]
            band = _clip_polyline_band(ring, max(z0, floor_top), wall_height)
            if len(band) >= 2 and abs(band[0][0] - band[-1][0]) < 1e-6 and abs(band[0][1] - band[-1][1]) < 1e-6:
                band = band[:-1]
            return band if len(band) >= 3 else []

        if square is None:
            holes.append(wall_segment(z0, z1))
            continue
        for za, zb in _z_finger_spans(z0, z1, pitch, 1.0 / cos_a):
            slot = wall_segment(za, zb)
            if slot:
                holes.append(slot)
    return [hole for hole in holes if hole]


def _leaned_end_edge(
    d: Divider,
    params: InsertParams,
    joints: List[_DivJoint],
    at_start: bool,
    x_mid: float,
    outward: float,
    y0: float,
    y1: float,
    cos_a: float,
    slant: float,
    tongue: float,
    pitch: float,
) -> Poly:
    """Bottom-to-top end of a leaned plate, in centerline X and slant Y."""
    thickness = params.thickness
    y_of = lambda z, base=y0, scale=cos_a: (z - base) / scale
    mate = _angled_stub_edge(
        joints, at_start, x_mid, outward, y0, y1, thickness, pitch, y_of, 1.0 / cos_a, 0.0, slant
    )
    if mate is not None:
        return mate
    if at_start:
        px, py, ox, oy = d.x1, d.y1, d.x2, d.y2
    else:
        px, py, ox, oy = d.x2, d.y2, d.x1, d.y1
    if _square_wall_hit(px, py, ox, oy, params) is not None and slant > tongue + 1.0:
        return _vertical_fingers(x_mid, tongue, slant, thickness, pitch, outward)
    if _loose_wall_hit(px, py, params) is not None:
        outer = x_mid + outward * thickness
        return [(x_mid, tongue), (outer, tongue), (outer, slant)]
    return [(x_mid, 0.0), (x_mid, slant)]


def _leaned_divider_plate(
    d: Divider,
    params: InsertParams,
    joints: List[_DivJoint],
    y0: float,
    y1: float,
) -> Tuple[Poly, List[Poly]]:
    """Flat pattern of a leaned divider. Local Y runs along the slant.

    The bottom is fingered into the floor when the plate includes the floor
    tongue. A square wall end is fingered. An end on another divider follows
    that divider's face, with fingers square to it.
    """
    cos_a = max(0.2, abs(math.cos(d.tilt_radians())))
    length = _divider_length(d)
    slant = (y1 - y0) / cos_a
    thickness = params.thickness
    floor_top = thickness if params.floor else 0.0
    tongue = floor_top / cos_a if params.floor and y0 <= 1e-6 else 0.0
    lid_tongue = (
        thickness / cos_a
        if params.closed_top() and d.top_fingers and y1 >= params.height - 1e-6
        else 0.0
    )
    end_pitch = (params.height - floor_top) / _odd_count(params.finger_count)
    bottom_pitch = params.height / _odd_count(params.finger_count)
    kerf = params.kerf
    t0, t1 = _floor_finger_limits(length, joints, thickness)
    along_spans = [(a + t0, b + t0) for a, b in _spans_for_length(max(0.0, t1 - t0), bottom_pitch)]
    finger_spans = along_spans if tongue > 0.0 else []
    top_spans = along_spans if lid_tongue > 0.0 else []
    bottom_notches: List[Tuple[float, float, float]] = []
    top_notches: List[Tuple[float, float, float]] = []
    holes: List[Poly] = []
    for joint in joints:
        half = (joint.width + kerf) / 2.0
        xa = joint.t - half
        xb = joint.t + half
        if joint.kind == "cross-bottom" and abs(joint.y0 - y0) <= 0.75:
            reach = max(0.0, min(slant, (joint.y1 - y0) / cos_a))
            bottom_notches.append((xa, xb, reach))
            continue
        if joint.kind == "cross-top" and abs(joint.y1 - y1) <= 0.75:
            reach = max(0.0, min(slant, (joint.y0 - y0) / cos_a))
            top_notches.append((xa, xb, reach))
            continue
        if joint.kind not in ("cross-bottom", "cross-top", "lean-slot"):
            continue
        ly0 = max(0.0, (joint.y0 - y0) / cos_a)
        ly1 = min(slant, (joint.y1 - y0) / cos_a)
        sx = max(0.0, xa)
        sw = min(length, xb) - sx
        if sw > 0.5 and ly1 > ly0 + 0.5:
            holes.append(_rect(sx, ly0, sw, ly1 - ly0))
    holes.extend(
        _lean_finger_holes(
            joints,
            0.0,
            lambda z, base=y0, scale=cos_a: (z - base) / scale,
            1.0 / cos_a,
            end_pitch,
            thickness,
            kerf,
        )
    )
    left = _leaned_end_edge(
        d, params, joints, True, 0.0, -1.0, y0, y1, cos_a, slant, tongue, end_pitch
    )
    right = _leaned_end_edge(
        d, params, joints, False, length, 1.0, y0, y1, cos_a, slant, tongue, end_pitch
    )
    gap_y = tongue if tongue > 0.0 else 0.0
    bottom = _notched_profile(length, finger_spans, bottom_notches, 0.0, gap_y, 0.0)
    if top_notches or lid_tongue > 0.0:
        top = list(reversed(_notched_profile(
            length,
            top_spans,
            top_notches,
            slant,
            slant - lid_tongue if lid_tongue > 0.0 else slant,
            slant,
        )))
    else:
        top = [(length, slant), (0.0, slant)]
    bottom, top = _attach_angled_ends(bottom, top, left or None, right or None)
    outline: Poly = []
    _append_unique(outline, bottom)
    _append_unique(outline, right)
    _append_unique(outline, top)
    _append_unique(outline, list(reversed(left)))
    return outline, holes


def _divider_end_slots_for_wall(
    wall_name: str,
    wall_length: float,
    wall_height: float,
    thickness: float,
    d: Divider,
    params: InsertParams,
) -> List[Poly]:
    """Finger notches where a divider end meets this wall. Angled ends keep a single slot."""
    if d.leans():
        return _leaned_wall_slots(wall_name, wall_length, wall_height, thickness, d, params)
    plate = d.plate_span(params.height, thickness, params.floor, params.closed_top())
    if plate is None:
        return []
    floor_top = thickness if params.floor else 0.0
    finger_lo = max(plate[0], floor_top)
    finger_hi = plate[1]
    if params.closed_top():
        finger_hi = min(finger_hi, params.height - params.thickness)
    pitch = (params.height - floor_top) / _odd_count(params.finger_count)
    holes: List[Poly] = []
    ends = (
        (d.x1, d.y1, d.x2, d.y2),
        (d.x2, d.y2, d.x1, d.y1),
    )
    for x, y, ox, oy in ends:
        square = _square_wall_hit(x, y, ox, oy, params)
        if square is not None and square[0] == wall_name:
            holes.extend(
                _finger_slots_between(
                    square[1],
                    wall_length,
                    thickness,
                    params.kerf,
                    finger_lo,
                    finger_hi,
                    pitch,
                    y_min=floor_top,
                )
            )
            continue
        loose = _loose_wall_hit(x, y, params)
        if loose is not None and loose[0] == wall_name and square is None:
            holes.append(
                _plain_slot_in_wall(
                    loose[1],
                    wall_length,
                    wall_height,
                    thickness,
                    params.kerf,
                    plate[0],
                    plate[1],
                )
            )
    return holes


def _translate(poly: Poly, origin: Vec2) -> Poly:
    ox, oy = origin
    return [(x + ox, y + oy) for x, y in poly]


def _custom_divider_name(label: str) -> str:
    """Name the user gave a divider. Blank, and d0, d1, … placeholders, stay unnamed."""
    text = " ".join((label or "").split())
    if not text or (text.startswith("d") and text[1:].isdigit()):
        return ""
    return text


# Extra room per side so a cap slips over the outside of the box.
_CAP_SLIP = 0.4


def _tab_leg(length: float, height: float, thickness: float, fingers: int, male: bool) -> Poly:
    """One leg of a corner tab. Fingers are on the left end; the other end is square."""
    count = _odd_count(fingers)
    while count > 1 and height / count < thickness * 0.6:
        count -= 2
    bottom = [(0.0, 0.0), (length, 0.0)]
    right = [(length, 0.0), (length, height)]
    top = [(length, height), (0.0, height)]
    if count >= 3 and height >= thickness * 2.0:
        raw = _finger_edge(height, thickness, count, male, 0.0)
        left = list(reversed([(y, x) for x, y in raw]))
    else:
        left = [(0.0, height), (0.0, 0.0)]
    outline: Poly = []
    _append_unique(outline, bottom)
    _append_unique(outline, right)
    _append_unique(outline, top)
    _append_unique(outline, left)
    return outline


_SLIDE_BEVEL = 0.6


def _latch_wall_holes(params: InsertParams, wall_name: str) -> List[Poly]:
    """Slots the lid tabs enter. The spring itself is cut in the lid."""
    if params.lid != "latch":
        return []
    latch_wall, stop_wall = params.latch_walls()
    if wall_name == stop_wall:
        spans = params.latch_back_tabs()
    elif wall_name == latch_wall:
        spans = params.latch_tab_spans()
    else:
        return []
    thickness = params.thickness
    slip = 0.3 + params.kerf
    return [
        _rect(left - slip / 2.0, params.height - slip / 2.0, right - left + slip, thickness + slip)
        for left, right in spans
    ]


def _latch_lid_holes(params: InsertParams) -> List[Poly]:
    """Serpentine and finger hole for each spring tab, in box coordinates.

    The cuts leave a zigzag of the lid leading out to the tab. Pulling the
    finger hole toward the middle shortens that zigzag and draws the tab out
    of the slot in the latch wall.
    """
    loops, beam, gap, width, _hole_r, _hole_cy, spring_y0 = params._latch_layout()
    if loops < 2 or width < 8.0 or beam < 0.6 or gap < 0.4:
        return list(params.latch_finger_holes(params.kerf))
    thickness = params.thickness
    holes: List[Poly] = []
    # Chamfer where a spring channel meets the lid edge, instead of a square corner
    # that sticks out past the tab.
    corner = 2.0

    def cut(across0: float, inward0: float, across1: float, inward1: float) -> None:
        if across1 - across0 < 0.3 or inward1 - inward0 < 0.3:
            return
        holes.append([
            params.latch_point(across0, inward0),
            params.latch_point(across1, inward0),
            params.latch_point(across1, inward1),
            params.latch_point(across0, inward1),
        ])

    def cut_poly(points: List[Tuple[float, float]]) -> None:
        holes.append([params.latch_point(u, v) for u, v in points])

    for center in params.latch_centers():
        x0 = center - width / 2.0
        x1 = center + width / 2.0

        def beam_y(index: int) -> float:
            return spring_y0 + index * (beam + gap)

        last = loops - 1
        last_top = beam_y(last) + beam
        connector_left = last % 2 == 0
        left_end = beam_y(last) if connector_left else last_top + gap
        right_end = last_top + gap if connector_left else beam_y(last)
        # The diagonal runs past the lid edge so the cut meets that edge in one
        # line. The inner wall follows the kerf-widened tab side, so the side
        # stays straight into the tip bevel instead of stepping out by a kerf.
        out = 0.4
        half = params.kerf / 2.0
        cut_poly([
            (x0 - half, thickness - 0.4),
            (x0 - half, left_end),
            (x0 - gap, left_end),
            (x0 - gap, thickness + corner),
            (x0 - gap - corner - out, thickness - out),
            (x0 - out, thickness - out),
        ])
        cut_poly([
            (x1 + out, thickness - out),
            (x1 + gap + corner + out, thickness - out),
            (x1 + gap, thickness + corner),
            (x1 + gap, right_end),
            (x1 + half, right_end),
            (x1 + half, thickness - 0.4),
        ])
        # The slots stop one beam short of the alternating side. No extra notch
        # there: that step left a corner thinner than the beam.
        for index in range(loops - 1):
            yg0 = beam_y(index) + beam
            yg1 = yg0 + gap
            if index % 2 == 0:
                cut(x0 + beam, yg0, x1 + half, yg1)
            else:
                cut(x0 - half, yg0, x1 - beam, yg1)
        if connector_left:
            cut(x0 + beam, last_top, x1 + gap, last_top + gap)
        else:
            cut(x0 - gap, last_top, x1 - beam, last_top + gap)
    holes.extend(params.latch_finger_holes(params.kerf))
    return holes


def _add_latch_lid(params: InsertParams, place) -> None:
    """One sheet. The spring tabs enter the chosen wall, and two plain tabs enter the opposite wall."""
    thickness = params.thickness
    across, along = params.latch_axes()
    pts: Poly = []

    def add(u: float, v: float) -> None:
        x, y = params.latch_point(u, v)
        if not pts or abs(pts[-1][0] - x) > 1e-9 or abs(pts[-1][1] - y) > 1e-9:
            pts.append((x, y))

    # Chamfer the outer corners of each tab, the end that enters the wall.
    # Leave the channel bevel at the lid edge as it is.
    tip = min(2.0, thickness - 0.8)

    def add_tip(u0: float, u1: float, root: float, end: float) -> None:
        """One tab, walked from u0 to u1. `end` is the outer edge; those corners are cut back."""
        span = abs(u1 - u0)
        cut = min(tip, span / 4.0)
        inward = 1.0 if end > root else -1.0
        across = 1.0 if u1 > u0 else -1.0
        add(u0, root)
        add(u0, end - inward * cut)
        add(u0 + across * cut, end)
        add(u1 - across * cut, end)
        add(u1, end - inward * cut)
        add(u1, root)

    add(thickness, thickness)
    for left, right in params.latch_tab_spans():
        add_tip(left, right, thickness, 0.0)
    add(across - thickness, thickness)
    add(across - thickness, along - thickness)
    for left, right in reversed(params.latch_back_tabs()):
        add_tip(right, left, along - thickness, along)
    add(thickness, along - thickness)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, miny = min(xs), min(ys)
    outline = _offset_kerf([(p[0] - minx, p[1] - miny) for p in pts], params.kerf, outward=True)
    holes = [[(x - minx, y - miny) for x, y in hole] for hole in _latch_lid_holes(params)]
    # The spring cuts overlap each other and the tab edge. Join them into that edge.
    outline, holes = _open_slots_into_outline(outline, holes, params.kerf)
    place("lid-latch", outline, holes, max(xs) - minx, max(ys) - miny, "Lid")


def _slide_slot_holes(params: InsertParams, wall_name: str) -> List[Poly]:
    """Drop-in slots in a side wall. The top is open, then the slot runs back.

    The open length is 1.1 times the tab. The closed length equals the tab, which
    is how far the lid slides. The front half of that closed slot tapers down to
    the material thickness. The back half stays at that thickness so it grips.
    Kerf is taken out of the path so the finished grip matches the sheet.
    """
    if params.lid != "slide":
        return []
    _stop, _entry, side_a, side_b = params.slide_roles()
    if wall_name not in (side_a, side_b):
        return []
    thickness = params.thickness
    half = params.kerf / 2.0
    base = params.height
    break_y = params.wall_height(wall_name) + 1.0
    y_bot = base + half
    y_tight = base + thickness - half
    y_wide = base + thickness + _SLIDE_BEVEL - half
    if y_tight <= y_bot + 0.2:
        return []
    holes: List[Poly] = []
    for start, end in params.slide_tabs():
        length = end - start
        opened = start - 1.1 * length
        mid = start + 0.5 * length

        def x_at(along: float) -> float:
            return params.slide_panel_x(along)

        holes.append(
            [
                (x_at(opened), y_bot),
                (x_at(opened), break_y),
                (x_at(start), break_y),
                (x_at(start), y_wide),
                (x_at(mid), y_tight),
                (x_at(end), y_tight),
                (x_at(end), y_bot),
            ]
        )
    return holes


def _add_slide_lid(params: InsertParams, place) -> None:
    """One sheet. The front reaches the outside of the entry wall. The back is plain."""
    a0, a1 = params.slide_body_across()
    outer0, outer1 = params.slide_outer_across()
    span = params.slide_span()
    tabs = params.slide_tabs()
    pts: Poly = []

    def add(along: float, across: float) -> None:
        point = params.slide_point(along, across)
        if not pts or abs(pts[-1][0] - point[0]) > 1e-9 or abs(pts[-1][1] - point[1]) > 1e-9:
            pts.append(point)

    add(0.0, a0)
    add(0.0, a1)
    for start, end in tabs:
        add(start, a1)
        add(start, outer1)
        add(end, outer1)
        add(end, a1)
    add(span, a1)
    add(span, a0)
    for start, end in reversed(tabs):
        add(end, a0)
        add(end, outer0)
        add(start, outer0)
        add(start, a0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, miny = min(xs), min(ys)
    outline = _offset_kerf([(p[0] - minx, p[1] - miny) for p in pts], params.kerf, outward=True)
    finger = params.slide_finger_hole(params.kerf)
    holes = [[(x - minx, y - miny) for x, y in finger]] if finger else []
    width = max(xs) - minx
    height = max(ys) - miny
    place("lid-slide", outline, holes, width, height, "Lid")


def _add_lid_panels(params: InsertParams, place) -> None:
    """Finger-jointed lid: a cap over the outside, or a same-size lid on the walls.

    A sit-on-top lid can include glue-on corner tabs at the corners you choose.
    Each tab is an L of two strips. The strips are tall enough to fill the lid
    and keep going down into the box. Inner and outer use the same pieces.
    """
    if params.lid == "none" or params.closed_top():
        return
    if params.lid == "slide":
        _add_slide_lid(params, place)
        return
    if params.lid == "latch":
        _add_latch_lid(params, place)
        return
    T = params.thickness
    fingers = params.finger_count
    kerf = params.kerf
    height = params.lid_height
    # The piece is the rim plus the fingers that pass through the lid panel,
    # the same way a box wall includes its joint into the floor.
    wall_h = height + T
    if params.lid == "cap":
        length = params.outer_length + 2.0 * (T + _CAP_SLIP)
        width = params.outer_width + 2.0 * (T + _CAP_SLIP)
    else:
        length = params.outer_length
        width = params.outer_width
    # Same pitch as the box floor, not a copy of the short lid side.
    pitch = params.height / _odd_count(fingers)
    length_spans = _floor_joint_spans(length, T, pitch, owns_corners=True)
    width_spans = _floor_joint_spans(width, T, pitch, owns_corners=False)
    wall_pitch = (params.height - T) / _odd_count(fingers)
    corner_count = _lid_corner_count(height, wall_pitch)
    panel = _offset_kerf(_floor_outline(length, width, T, length_spans, width_spans), kerf, outward=True)
    place("lid-panel", panel, [], length, width, "Lid")
    for name, edge, left_male, right_male, spans in [
        ("lid-front", length, True, True, length_spans),
        ("lid-back", length, False, False, length_spans),
        ("lid-left", width, True, False, width_spans),
        ("lid-right", width, False, True, width_spans),
    ]:
        outline = _offset_kerf(
            _wall_panel_outline(edge, wall_h, T, fingers, left_male, right_male, spans or None, corner_count),
            kerf,
            outward=True,
        )
        place(name, outline, [], edge + 2.0 * T, wall_h + T, "Lid " + name.split("-", 1)[1])
    if params.lid != "top" or not params.lid_tabs:
        return
    leg = params.alignment_leg()
    tab_h = params.alignment_strip_height()
    for n, corner in enumerate(params.lid_tab_corners):
        male_first = n % 2 == 0
        for index, male in enumerate((male_first, not male_first)):
            outline = _offset_kerf(_tab_leg(leg, tab_h, T, fingers, male), kerf, outward=True)
            place(
                f"tab-{corner}-{index}",
                outline,
                [],
                leg + T,
                tab_h,
                f"Tab {corner}",
            )


def piece_label(name: str, label: str = "") -> str:
    """Human-readable name for a nested panel.

    A divider name is drawn as the user typed it. With no name, the piece is
    Divider 1, Divider 2, and so on, in divider order.
    """
    if name == "floor":
        return "Floor"
    if name.startswith("wall-"):
        return "Wall " + name.split("-", 1)[1]
    if name.startswith("lid-") or name.startswith("tab-"):
        return label or name.replace("-", " ")
    if name.startswith("divider-"):
        custom = _custom_divider_name(label)
        if custom:
            return custom
        rest = name[len("divider-") :]
        idx, _, encoded = rest.partition("-")
        # Older nests packed the name into the panel id, after the index.
        custom = _custom_divider_name(encoded.replace("-", " "))
        if custom and encoded != idx:
            return custom
        try:
            n = int(idx) + 1
        except ValueError:
            n = idx
        return f"Divider {n}"
    return name.replace("-", " ")


def panel_label(panel: Panel) -> Tuple[str, float, Vec2]:
    """Name, font size in mm, and an anchor in panel-local coordinates."""
    xs = [p[0] for p in panel.outline]
    ys = [p[1] for p in panel.outline]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    text = piece_label(panel.name, panel.label)
    font = _label_font_mm(text, width, height)
    anchor = _label_anchor(
        panel.holes,
        (min(xs) + max(xs)) / 2.0,
        (min(ys) + max(ys)) / 2.0,
        width,
        height,
        font,
    )
    return text, font, anchor


def _label_font_mm(text: str, width: float, height: float) -> float:
    """Font size in mm that stays inside the piece."""
    size = min(6.0, height * 0.28)
    if text:
        size = min(size, (width * 0.82) / (len(text) * 0.55))
    return max(2.2, size)


def _point_in_poly(x: float, y: float, poly: Poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            x_cross = (x1 - x0) * (y - y0) / (y1 - y0) + x0
            if x < x_cross:
                inside = not inside
    return inside


def _label_anchor(
    holes: List[Poly],
    cx: float,
    cy: float,
    width: float,
    height: float,
    font: float,
) -> Vec2:
    """Prefer the piece center, stepping away from slots so the name stays readable."""
    pad = font * 0.65
    steps = (0.0, 1.6, -1.6, 3.2, -3.2)
    for sy in steps:
        for sx in steps:
            x = cx + sx * font
            y = cy + sy * font
            if abs(x - cx) > width * 0.42 or abs(y - cy) > height * 0.42:
                continue
            samples = ((x, y), (x - pad, y), (x + pad, y), (x, y - pad), (x, y + pad))
            if all(not any(_point_in_poly(px, py, hole) for hole in holes) for px, py in samples):
                return (x, y)
    return (cx, cy)


def export_svg(params: InsertParams, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    panels = build_panels(params)
    # Bounds
    max_x = max((o[0] + max(p[0] for p in panel.outline) for panel in panels for o in [panel.origin]), default=100.0)
    max_y = max((o[1] + max(p[1] for p in panel.outline) for panel in panels for o in [panel.origin]), default=100.0)
    # SVG Y-down: flip for readability (laser software often Y-up; we note in docs)
    dwg = svgwrite.Drawing(
        str(path),
        size=(f"{max_x + 10:.2f}mm", f"{max_y + 10:.2f}mm"),
        viewBox=f"0 0 {max_x + 10} {max_y + 10}",
    )
    g = dwg.g(id="cut", fill="none", stroke="black", stroke_width=0.1)
    labels = dwg.g(id="labels", fill="#1d4e89", stroke="none", font_family="sans-serif")
    for panel in panels:
        pts = _translate(panel.outline, panel.origin)
        g.add(dwg.polygon(points=[(f"{x:.4f}", f"{y:.4f}") for x, y in pts]))
        for hole in panel.holes:
            hpts = _translate(hole, panel.origin)
            g.add(dwg.polygon(points=[(f"{x:.4f}", f"{y:.4f}") for x, y in hpts]))
        text, font, (lx, ly) = panel_label(panel)
        cx = panel.origin[0] + lx
        cy = panel.origin[1] + ly
        labels.add(
            dwg.text(
                text,
                insert=(f"{cx:.3f}", f"{cy:.3f}"),
                text_anchor="middle",
                dominant_baseline="central",
                font_size=f"{font:.2f}",
            )
        )
    dwg.add(g)
    dwg.add(labels)
    dwg.save()
    return path


def export_dxf(params: InsertParams, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    panels = build_panels(params)
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.units = ezdxf.units.MM
    for panel in panels:
        pts = _translate(panel.outline, panel.origin)
        # close
        if pts[0] != pts[-1]:
            pts = pts + [pts[0]]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "CUT"})
        for hole in panel.holes:
            hpts = _translate(hole, panel.origin)
            if hpts[0] != hpts[-1]:
                hpts = hpts + [hpts[0]]
            msp.add_lwpolyline(hpts, close=True, dxfattribs={"layer": "CUT"})
    doc.saveas(str(path))
    return path
