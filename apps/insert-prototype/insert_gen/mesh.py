"""3D mesh generation for STL export (numpy-stl)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import numpy as np
from stl import mesh

from .model import Divider, InsertParams

Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]
Tri = Tuple[Vec3, Vec3, Vec3]


def _box_tris(x0: float, y0: float, z0: float, dx: float, dy: float, dz: float) -> List[Tri]:
    """Axis-aligned box as 12 triangles."""
    x1, y1, z1 = x0 + dx, y0 + dy, z0 + dz
    v = {
        "000": (x0, y0, z0),
        "100": (x1, y0, z0),
        "010": (x0, y1, z0),
        "110": (x1, y1, z0),
        "001": (x0, y0, z1),
        "101": (x1, y0, z1),
        "011": (x0, y1, z1),
        "111": (x1, y1, z1),
    }
    faces = [
        ("000", "100", "110"),
        ("000", "110", "010"),  # bottom
        ("001", "011", "111"),
        ("001", "111", "101"),  # top
        ("000", "010", "011"),
        ("000", "011", "001"),  # -X
        ("100", "101", "111"),
        ("100", "111", "110"),  # +X
        ("000", "001", "101"),
        ("000", "101", "100"),  # -Y
        ("010", "110", "111"),
        ("010", "111", "011"),  # +Y
    ]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def _extrude_polygon(poly: Sequence[Vec2], z0: float, z1: float) -> List[Tri]:
    """Extrude a simple convex polygon (CCW) into a prism."""
    pts = list(poly)
    n = len(pts)
    if n < 3:
        return []
    tris: List[Tri] = []
    # Bottom (CW when viewed from +Z so normal points down)
    for i in range(1, n - 1):
        tris.append(((pts[0][0], pts[0][1], z0), (pts[i + 1][0], pts[i + 1][1], z0), (pts[i][0], pts[i][1], z0)))
    # Top
    for i in range(1, n - 1):
        tris.append(((pts[0][0], pts[0][1], z1), (pts[i][0], pts[i][1], z1), (pts[i + 1][0], pts[i + 1][1], z1)))
    # Sides
    for i in range(n):
        j = (i + 1) % n
        a = (pts[i][0], pts[i][1], z0)
        b = (pts[j][0], pts[j][1], z0)
        c = (pts[j][0], pts[j][1], z1)
        d = (pts[i][0], pts[i][1], z1)
        tris.append((a, b, c))
        tris.append((a, c, d))
    return tris


def _loft_quads(bottom: Sequence[Vec3], top: Sequence[Vec3]) -> List[Tri]:
    """Solid between two quads. Matching corners share an edge."""
    n = len(bottom)
    if n < 3 or len(top) != n:
        return []
    tris: List[Tri] = []
    for i in range(1, n - 1):
        tris.append((bottom[0], bottom[i + 1], bottom[i]))
        tris.append((top[0], top[i], top[i + 1]))
    for i in range(n):
        j = (i + 1) % n
        tris.append((bottom[i], bottom[j], top[j]))
        tris.append((bottom[i], top[j], top[i]))
    return tris


def _end_follow(
    d: Divider, at_start: bool, params: InsertParams
) -> Tuple[float, float] | None:
    """How this end moves along its length to stay on a leaned divider.

    Returns (millimetres along this centerline per millimetre of height, pivot
    height). The end meets the other divider's midplane, so the 3D edge shows
    the same angle as the laser joint.
    """
    px, py = (d.x1, d.y1) if at_start else (d.x2, d.y2)
    dx, dy = d.x2 - d.x1, d.y2 - d.y1
    length = float(np.hypot(dx, dy))
    if length < 1e-6:
        return None
    ux, uy = dx / length, dy / length
    best: Tuple[float, float] | None = None
    best_dist = 1.5
    for other in params.dividers:
        if other is d or not other.leans():
            continue
        odx, ody = other.x2 - other.x1, other.y2 - other.y1
        olen = float(np.hypot(odx, ody))
        if olen < 1e-6:
            continue
        oux, ouy = odx / olen, ody / olen
        along = (px - other.x1) * oux + (py - other.y1) * ouy
        dist = float(np.hypot(px - (other.x1 + oux * along), py - (other.y1 + ouy * along)))
        margin = max(params.thickness, 2.0)
        if dist > best_dist or not (margin < along < olen - margin):
            continue
        onx, ony = -ouy, oux
        dot = ux * onx + uy * ony
        if abs(dot) < 0.25:
            continue
        span = other.plate_span(params.height, params.thickness, params.floor)
        if span is None:
            continue
        best = (math.tan(other.tilt_radians()) / dot, span[0])
        best_dist = dist
    return best


def _divider_prism(d: Divider, thickness: float, z0: float, z1: float, params: InsertParams) -> List[Tri]:
    """Plate along the divider centerline. A tilt leans it off vertical.

    An end that meets a leaned divider follows that face, so the end edge is
    cut on the same angle instead of staying vertical.
    """
    x1, y1, x2, y2 = d.x1, d.y1, d.x2, d.y2
    dx, dy = x2 - x1, y2 - y1
    length = float(np.hypot(dx, dy))
    if length < 1e-6 or z1 <= z0:
        return []
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    h = thickness / 2.0
    follow_start = _end_follow(d, True, params)
    follow_end = _end_follow(d, False, params)
    if not d.leans() and follow_start is None and follow_end is None:
        # Extend slightly into walls for a solid joint.
        poly = [
            (x1 - ux * 0.01 - nx * h, y1 - uy * 0.01 - ny * h),
            (x2 + ux * 0.01 - nx * h, y2 + uy * 0.01 - ny * h),
            (x2 + ux * 0.01 + nx * h, y2 + uy * 0.01 + ny * h),
            (x1 - ux * 0.01 + nx * h, y1 - uy * 0.01 + ny * h),
        ]
        return _extrude_polygon(poly, z0, z1)

    alpha = d.tilt_radians()
    # Thickness stays perpendicular to the leaned plate.
    cos_a = math.cos(alpha)
    sin_a = math.sin(alpha)
    tx, ty, tz = uy * cos_a, -ux * cos_a, sin_a
    tan_a = math.tan(alpha)
    # Pivot on the bottom of the plate. A fingered floor joint includes the
    # tongue through the floor, so that pivot is at z=0.
    span_anchor = 0.0 if d.bottom <= 1e-6 and d.floor_fingers else z0

    def corner(px: float, py: float, z: float, face: float) -> Vec3:
        shift = (z - span_anchor) * tan_a
        return (
            px + nx * shift + tx * h * face,
            py + ny * shift + ty * h * face,
            z + tz * h * face,
        )

    def end_xy(at_start: bool, z: float, follow: Tuple[float, float] | None) -> Vec2:
        px, py = (x1, y1) if at_start else (x2, y2)
        if follow is None:
            sign = -1.0 if at_start else 1.0
            return px + ux * 0.01 * sign, py + uy * 0.01 * sign
        coef, anchor = follow
        delta = coef * (z - anchor)
        return px + ux * delta, py + uy * delta

    def quad(z: float) -> List[Vec3]:
        ax, ay = end_xy(True, z, follow_start)
        bx, by = end_xy(False, z, follow_end)
        return [
            corner(ax, ay, z, -1),
            corner(bx, by, z, -1),
            corner(bx, by, z, 1),
            corner(ax, ay, z, 1),
        ]

    return _loft_quads(quad(z0), quad(z1))


def build_print_parts(params: InsertParams) -> List[Tuple[str, List[Tri]]]:
    """Print solid split into the box body and one part per divider, in divider order."""
    body: List[Tri] = []
    if params.floor:
        body.extend(_box_tris(0, 0, 0, params.outer_length, params.outer_width, params.thickness))
        z0 = params.thickness
    else:
        z0 = 0.0
    L, W, T = params.outer_length, params.outer_width, params.thickness

    def wall_dz(name: str) -> float:
        return params.wall_height(name) - z0

    body.extend(_box_tris(0, 0, z0, L, T, wall_dz("wall-front")))
    body.extend(_box_tris(0, W - T, z0, L, T, wall_dz("wall-back")))
    body.extend(_box_tris(0, T, z0, T, W - 2 * T, wall_dz("wall-left")))
    body.extend(_box_tris(L - T, T, z0, T, W - 2 * T, wall_dz("wall-right")))
    parts: List[Tuple[str, List[Tri]]] = [("body", body)]
    lid = _lid_tris(params)
    if lid:
        parts.append(("lid", lid))
    for i, d in enumerate(params.dividers):
        span = d.print_span(params.height, params.thickness, params.floor)
        prism = (
            _divider_prism(d, params.thickness, span[0], span[1], params) if span is not None else []
        )
        parts.append((f"divider-{i}", prism))
    return parts


def _lid_tris(params: InsertParams) -> List[Tri]:
    """Solid lid, without finger cutouts. A cap hangs over the outside.

    A sit-on-top lid matches the box footprint. Its rim hangs down onto the
    walls, so the opening faces the box and the panel closes the top.
    Alignment tabs run through that lid space and on down into the box.
    """
    if params.lid == "none":
        return []
    if params.lid == "slide":
        return _slide_lid_tris(params)
    if params.lid == "latch":
        return _latch_lid_tris(params)
    T = params.thickness
    lip = params.lid_height
    box_h = params.height
    # A hair of air so the lid does not flicker against the wall tops.
    seat = box_h + 0.25
    if params.lid == "cap":
        slip = 0.4
        ox = -(T + slip)
        oy = -(T + slip)
        length = params.outer_length + 2.0 * (T + slip)
        width = params.outer_width + 2.0 * (T + slip)
        wall_z = box_h - lip
        panel_z = seat
    else:
        ox = oy = 0.0
        length = params.outer_length
        width = params.outer_width
        # Rim hangs down to the wall tops. The opening faces the box.
        wall_z = seat
        panel_z = seat + lip
    tris: List[Tri] = []
    tris.extend(_box_tris(ox, oy, panel_z, length, width, T))
    tris.extend(_box_tris(ox, oy, wall_z, length, T, lip))
    tris.extend(_box_tris(ox, oy + width - T, wall_z, length, T, lip))
    tris.extend(_box_tris(ox, oy + T, wall_z, T, width - 2.0 * T, lip))
    tris.extend(_box_tris(ox + length - T, oy + T, wall_z, T, width - 2.0 * T, lip))
    if params.lid == "top" and params.lid_tabs:
        tris.extend(_lid_tab_tris(params))
    return tris


def _cross2(o: Vec2, a: Vec2, b: Vec2) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _signed_area(poly: Sequence[Vec2]) -> float:
    area = 0.0
    for i, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(i + 1) % len(poly)]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _ccw(poly: Sequence[Vec2]) -> List[Vec2]:
    pts = list(poly)
    if _signed_area(pts) < 0.0:
        pts.reverse()
    return pts


def _axis_side(nx: float, ny: float) -> str:
    """Which way an outward normal points, in the four axis directions."""
    if abs(nx) >= abs(ny):
        return "right" if nx > 0.0 else "left"
    return "back" if ny > 0.0 else "front"


def _ear_clip(poly: Sequence[Vec2]) -> List[Tuple[Vec2, Vec2, Vec2]] | None:
    """Triangles of one simple CCW polygon, or None if it cannot be finished."""
    pts = [
        p
        for i, p in enumerate(poly)
        if i == 0 or abs(p[0] - poly[i - 1][0]) > 1e-8 or abs(p[1] - poly[i - 1][1]) > 1e-8
    ]
    if len(pts) >= 2 and abs(pts[0][0] - pts[-1][0]) < 1e-8 and abs(pts[0][1] - pts[-1][1]) < 1e-8:
        pts.pop()
    if len(pts) < 3:
        return []

    def contains(p: Vec2, a: Vec2, b: Vec2, c: Vec2) -> bool:
        if min(
            (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2,
            (p[0] - b[0]) ** 2 + (p[1] - b[1]) ** 2,
            (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2,
        ) < 1e-12:
            return False
        ab, bc, ca = _cross2(a, b, p), _cross2(b, c, p), _cross2(c, a, p)
        return ab > 1e-8 and bc > 1e-8 and ca > 1e-8

    tris: List[Tuple[Vec2, Vec2, Vec2]] = []
    guard = 0
    while len(pts) > 3 and guard < 500:
        guard += 1
        n = len(pts)
        clipped = False
        for i in range(n):
            prev, cur, nxt = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
            if _cross2(prev, cur, nxt) <= 1e-8:
                continue
            if any(contains(pts[j], prev, cur, nxt) for j in range(n) if j not in ((i - 1) % n, i, (i + 1) % n)):
                continue
            tris.append((prev, cur, nxt))
            del pts[i]
            clipped = True
            break
        if not clipped:
            return None
    if len(pts) == 3:
        tris.append((pts[0], pts[1], pts[2]))
    return tris


def _pockets(rect: Sequence[Vec2], hole: Sequence[Vec2]) -> List[List[Vec2]] | None:
    """Four side regions of an axis-aligned rectangle around a convex hole.

    Each hole edge is given to the rectangle side its outward normal faces.
    The extra vertex at the end of a run is shared with the next side, so the
    regions meet without a gap.
    """
    n = len(hole)
    owned: List[str] = []
    for i in range(n):
        prv, cur, nxt = hole[(i - 1) % n], hole[i], hole[(i + 1) % n]
        e1 = (cur[0] - prv[0], cur[1] - prv[1])
        e2 = (nxt[0] - cur[0], nxt[1] - cur[1])
        owned.append(_axis_side(e1[1] + e2[1], -(e1[0] + e2[0])))
    pockets: List[List[Vec2]] = []
    for e in range(4):
        start_pt, end_pt = rect[e], rect[(e + 1) % 4]
        name = _axis_side(end_pt[1] - start_pt[1], -(end_pt[0] - start_pt[0]))
        start = next((i for i in range(n) if owned[i] == name and owned[(i - 1) % n] != name), None)
        if start is None:
            return None
        chain: List[Vec2] = []
        i = start
        while len(chain) <= n:
            chain.append(hole[i])
            if owned[i] != name:
                break
            i = (i + 1) % n
        poly = [start_pt, end_pt] + list(reversed(chain))
        clean = [poly[0]]
        for point in poly[1:]:
            if (point[0] - clean[-1][0]) ** 2 + (point[1] - clean[-1][1]) ** 2 > 1e-12:
                clean.append(point)
        if (clean[0][0] - clean[-1][0]) ** 2 + (clean[0][1] - clean[-1][1]) ** 2 < 1e-12:
            clean.pop()
        pockets.append(clean)
    return pockets


def _loop_walls(poly: Sequence[Vec2], z0: float, z1: float) -> List[Tri]:
    """Side faces of a CCW loop. Normals point outward."""
    pts = list(poly)
    n = len(pts)
    tris: List[Tri] = []
    for i in range(n):
        j = (i + 1) % n
        a = (pts[i][0], pts[i][1], z0)
        b = (pts[j][0], pts[j][1], z0)
        c = (pts[j][0], pts[j][1], z1)
        d = (pts[i][0], pts[i][1], z1)
        tris.append((a, b, c))
        tris.append((a, c, d))
    return tris


def _plate_with_hole(outer: Sequence[Vec2], hole: Sequence[Vec2], z0: float, z1: float) -> List[Tri] | None:
    """A flat plate with a convex hole through it. None if the mesh cannot be built."""
    rim = _ccw(outer)
    opening = _ccw(hole)
    pockets = _pockets(rim, opening)
    if pockets is None:
        return None
    faces: List[Tuple[Vec2, Vec2, Vec2]] = []
    for pocket in pockets:
        clipped = _ear_clip(pocket)
        if clipped is None:
            return None
        faces.extend(clipped)
    tris: List[Tri] = []
    for a, b, c in faces:
        if abs(_cross2(a, b, c)) < 1e-6:
            continue
        tris.append(((a[0], a[1], z1), (b[0], b[1], z1), (c[0], c[1], z1)))
        tris.append(((a[0], a[1], z0), (c[0], c[1], z0), (b[0], b[1], z0)))
    tris.extend(_loop_walls(rim, z0, z1))
    tris.extend(_loop_walls(list(reversed(opening)), z0, z1))
    return tris


def _slide_lid_tris(params: InsertParams) -> List[Tri]:
    """The sheet in its closed position, with the side tabs in the walls.

    It sits on the entry wall. The slotted walls and the stop wall stand two
    thicknesses above it. The finger hole is cut through the sheet. The wall
    slots are cut only in the laser file.
    """
    thickness = params.thickness
    z = params.height + 0.2
    a0, a1 = params.slide_body_across()
    outer0, outer1 = params.slide_outer_across()
    span = params.slide_span()
    tris: List[Tri] = []

    def add_span(along0: float, along1: float, across0: float, across1: float) -> None:
        p0 = params.slide_point(along0, across0)
        p1 = params.slide_point(along1, across1)
        x0, x1 = sorted((p0[0], p1[0]))
        y0, y1 = sorted((p0[1], p1[1]))
        tris.extend(_box_tris(x0, y0, z, x1 - x0, y1 - y0, thickness))

    hole = params.slide_finger_hole()
    outer = [
        params.slide_point(0.0, a0),
        params.slide_point(0.0, a1),
        params.slide_point(span, a1),
        params.slide_point(span, a0),
    ]
    if hole:
        tris.extend(_plate_with_hole(outer, hole, z, z + thickness))
    else:
        add_span(0.0, span, a0, a1)
    for start, end in params.slide_tabs():
        add_span(start, end, a0, outer0)
        add_span(start, end, a1, outer1)
    return tris


def _latch_lid_tris(params: InsertParams) -> List[Tri]:
    """The lid sheet, with the front tabs in the front wall and a finger hole in each.

    The serpentine that lets those tabs pull inward is cut only in the laser file.
    """
    thickness = params.thickness
    z = params.height + 0.2
    length, width = params.outer_length, params.outer_width
    tris: List[Tri] = []
    body = [
        (thickness, thickness),
        (length - thickness, thickness),
        (length - thickness, width - thickness),
        (thickness, width - thickness),
    ]
    holes = params.latch_finger_holes()
    if len(holes) == 1:
        plate = _plate_with_hole(body, holes[0], z, z + thickness)
        tris.extend(plate or _box_tris(thickness, thickness, z, length - 2.0 * thickness, width - 2.0 * thickness, thickness))
    elif len(holes) >= 2:
        mid = length / 2.0
        for hole in holes:
            cx = sum(point[0] for point in hole) / len(hole)
            if cx < mid:
                rect = [(thickness, thickness), (mid, thickness), (mid, width - thickness), (thickness, width - thickness)]
            else:
                rect = [(mid, thickness), (length - thickness, thickness), (length - thickness, width - thickness), (mid, width - thickness)]
            plate = _plate_with_hole(rect, hole, z, z + thickness)
            span = rect[1][0] - rect[0][0]
            tris.extend(plate or _box_tris(rect[0][0], thickness, z, span, width - 2.0 * thickness, thickness))
    else:
        tris.extend(_box_tris(thickness, thickness, z, length - 2.0 * thickness, width - 2.0 * thickness, thickness))
    for left, right in params.latch_tab_spans():
        tris.extend(_box_tris(left, 0.0, z, right - left, thickness, thickness))
    for left, right in params.latch_back_tabs():
        tris.extend(_box_tris(left, width - thickness, z, right - left, thickness, thickness))
    return tris


def _lid_tab_tris(params: InsertParams) -> List[Tri]:
    """L-shaped tabs at the chosen corners, inside or outside the walls.

    Each strip overlaps the walls so the preview shows it meeting them, and
    the two strips of an L overlap each other at the corner. Vertically the
    tab fills the lid, up to the panel, and continues down into the box.
    """
    if not params.lid_tab_corners:
        return []
    T = params.thickness
    leg = params.alignment_leg()
    drop = params.lid_tab_height
    # Reach the underside of the lid panel, including the small seating gap.
    z0 = params.height - drop
    dz = drop + params.lid_height + 0.25
    L, W = params.outer_length, params.outer_width
    tris: List[Tri] = []
    for corner in params.lid_tab_corners:
        for x, y, dx, dy in _tab_legs(corner, params.lid_tab_fit, L, W, T, leg):
            tris.extend(_box_tris(x, y, z0, dx, dy, dz))
    return tris


def _tab_legs(
    corner: str, fit: str, length: float, width: float, thickness: float, leg: float
) -> List[Tuple[float, float, float, float]]:
    """Two overlapping strips of an L. They bite into the wall so they meet it."""
    bite = 0.6
    t = thickness
    L, W = length, width
    if fit == "outer":
        legs = {
            "front-left": ((-bite, -t, leg + bite, t + bite), (-t, -bite, t + bite, leg + bite)),
            "front-right": ((L - leg, -t, leg + bite, t + bite), (L - bite, -bite, t + bite, leg + bite)),
            "back-left": ((-bite, W - bite, leg + bite, t + bite), (-t, W - leg, t + bite, leg + bite)),
            "back-right": ((L - leg, W - bite, leg + bite, t + bite), (L - bite, W - leg, t + bite, leg + bite)),
        }
    else:
        legs = {
            "front-left": ((t - bite, t - bite, leg, t), (t - bite, t - bite, t, leg)),
            "front-right": ((L - t + bite - leg, t - bite, leg, t), (L - 2 * t + bite, t - bite, t, leg)),
            "back-left": ((t - bite, W - 2 * t + bite, leg, t), (t - bite, W - t + bite - leg, t, leg)),
            "back-right": (
                (L - t + bite - leg, W - 2 * t + bite, leg, t),
                (L - 2 * t + bite, W - t + bite - leg, t, leg),
            ),
        }
    return list(legs[corner])


def build_print_tris(params: InsertParams) -> List[Tri]:
    """Assemble print solid: optional floor + walls + dividers."""
    tris: List[Tri] = []
    for _, part in build_print_parts(params):
        tris.extend(part)
    return tris


def tris_to_mesh(tris: Iterable[Tri]) -> mesh.Mesh:
    tri_list = list(tris)
    data = np.zeros(len(tri_list), dtype=mesh.Mesh.dtype)
    for i, (a, b, c) in enumerate(tri_list):
        data["vectors"][i] = np.array([a, b, c], dtype=np.float64)
    m = mesh.Mesh(data, remove_empty_areas=False)
    m.update_normals()
    return m


def export_stl(params: InsertParams, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    m = tris_to_mesh(build_print_tris(params))
    m.save(str(path))
    return path
