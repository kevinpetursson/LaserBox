"""Shared insert parameters."""

from __future__ import annotations

import math
from typing import List, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Divider(BaseModel):
    """Divider centerline in insert-local coordinates (mm).

    Origin is the outer bottom-left corner of the insert. The editor shows these
    measured from the inner faces, shifted in by the material thickness.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    label: str = Field(
        "",
        description="Name drawn on this divider in the 2D drawing. Blank shows Divider 1, Divider 2, and so on.",
    )
    bottom: float = Field(
        0.0,
        ge=0,
        description="Gap above the floor (mm). 0 sits on the floor.",
    )
    top: float = Field(
        0.0,
        ge=0,
        description="Gap below the top of the box (mm). 0 reaches the top.",
    )
    tilt: float = Field(
        0.0,
        ge=-75.0,
        le=75.0,
        description="Lean away from vertical, in degrees. 0 stands perpendicular to the floor.",
    )
    floor_fingers: bool = Field(
        True,
        description="Finger-joint a divider that sits on the floor into the floor panel. "
        "Off rests that divider on the floor with a straight edge and no floor slots.",
    )
    top_fingers: bool = Field(
        True,
        description="Finger-joint a divider that reaches the top into a closed-box lid. "
        "Off stops that divider under the lid with a straight edge and no lid slots.",
    )

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        return " ".join(value.split())[:40]

    def tilt_radians(self) -> float:
        deg = min(75.0, max(-75.0, self.tilt))
        return math.radians(deg)

    def leans(self) -> bool:
        """True when the divider is rotated off perpendicular to the floor."""
        return abs(self.tilt) > 0.05

    def plate_span(
        self, height: float, thickness: float, floor: bool, closed: bool = False
    ) -> tuple[float, float] | None:
        """Laser plate extent. Y=0 is the bottom of the floor.

        A divider that sits on the floor includes the fingers that pass through it,
        unless `floor_fingers` is off. Then it starts on top of the floor and the
        bottom edge stays straight. A raised divider starts above the floor and has
        no floor joint. `top` shortens it down from the wall top. A closed lid sits
        in the top thickness of that height. Fingers pass through it only when the
        divider reaches the top and `top_fingers` is on. Otherwise the plate stops
        at the underside of the lid. Returns None when the two gaps leave no plate.
        """
        floor_top = thickness if floor else 0.0
        y1 = height - max(0.0, self.top)
        if closed and self.top_fingers and self.top <= 1e-6:
            y1 = height
        elif closed:
            y1 = min(y1, height - thickness)
        if floor and self.floor_fingers and self.bottom <= 1e-6:
            y0 = 0.0
        else:
            y0 = floor_top + max(0.0, self.bottom)
        if y1 < y0 + 1.0:
            return None
        return (y0, y1)

    def print_span(
        self, height: float, thickness: float, floor: bool, closed: bool = False
    ) -> tuple[float, float] | None:
        """Printed divider. It sits on the floor and stops under a closed lid."""
        floor_top = thickness if floor else 0.0
        z0 = floor_top + max(0.0, self.bottom)
        z1 = height - max(0.0, self.top)
        if closed:
            z1 = min(z1, height - thickness)
        if z1 < z0 + 0.5:
            return None
        return (z0, z1)


class InsertParams(BaseModel):
    """Parametric insert. Length and width are the outside dimensions."""

    length: float = Field(280.0, gt=10, description="Outside length (mm)")
    width: float = Field(200.0, gt=10, description="Outside width (mm)")
    height: float = Field(50.0, gt=5, description="Outside height, from the bottom of the box to the top of the walls")
    thickness: float = Field(3.0, ge=3.0, le=6.0, description="Material thickness (mm)")
    kerf: float = Field(0.15, ge=0, description="Laser kerf compensation (mm)")
    floor: bool = Field(True, description="Include floor (print); default on")
    finger_length: float = Field(
        10.0,
        ge=4.0,
        le=40.0,
        description="Approximate length of one finger (mm). Each edge uses the nearest odd count.",
    )
    lid: Literal["none", "cap", "top", "slide", "latch", "closed"] = Field(
        "none",
        description="none, a cap, a lid that sits on the walls, a tab-and-slot sheet, a spring latch, or a finger-jointed closed top",
    )
    lid_height: float = Field(
        15.0,
        gt=0,
        le=80.0,
        description="Inside depth of the lid, up to the underside of the panel",
    )
    lid_tabs: bool = Field(
        False,
        description="Glue-on L tabs at corners of a sit-on-top lid",
    )
    lid_tab_height: float = Field(
        12.0,
        gt=0,
        le=40.0,
        description="How far the alignment tabs drop into the box",
    )
    lid_tab_fit: Literal["inner", "outer"] = Field(
        "inner",
        description="Tabs sit inside the box corners or outside them",
    )
    lid_tab_corners: List[Literal["front-left", "front-right", "back-left", "back-right"]] = Field(
        default_factory=lambda: ["front-left", "back-right"],
        description="Corners that receive an alignment tab",
    )
    lid_slide: Literal["back", "front", "left", "right"] = Field(
        "back",
        description="Wall the tab-and-slot lid slides toward",
    )
    lid_slide_count: int = Field(2, ge=2, le=3, description="Tabs along each side of a tab-and-slot lid")
    lid_slide_tab: float = Field(20.0, gt=0, le=80.0, description="Length of each tab on a tab-and-slot lid")
    lid_latch_side: Literal["back", "front", "left", "right"] = Field(
        "front",
        description="Wall the latch spring tabs enter. The two plain tabs are on the opposite wall",
    )
    lid_latch_count: int = Field(1, ge=1, le=2, description="Spring tabs on the latch wall")
    lid_latch_loops: int = Field(4, ge=2, le=8, description="Serpentine loops under each latch tab")
    lid_latch_beam: float = Field(2.0, ge=1.0, le=4.0, description="Wood left between the latch cuts")
    lid_latch_width: float = Field(30.0, ge=14.0, le=80.0, description="Width of one latch spring")
    dividers: List[Divider] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_lid_minimums(self) -> InsertParams:
        if self.lid_height + 1e-6 < self.thickness:
            raise ValueError("Lid side height must be at least the material thickness")
        if self.lid_tab_height + 1e-6 < self.thickness:
            raise ValueError("Tab height must be at least the material thickness")
        return self

    @field_validator("lid_tab_corners")
    @classmethod
    def _unique_corners(cls, value: List[str]) -> List[str]:
        order = ("front-left", "front-right", "back-left", "back-right")
        picked = set(value)
        return [corner for corner in order if corner in picked]

    def alignment_leg(self) -> float:
        """Length of one strip in a corner tab, kept short so it stays in the corner."""
        leg = min(24.0, max(12.0, 4.0 * self.thickness))
        short = min(self.inner_length, self.inner_width)
        if short > 8.0:
            leg = min(leg, short * 0.45)
        return leg

    def alignment_strip_height(self) -> float:
        """The strip fills the lid and continues this far down into the box."""
        return self.lid_height + self.lid_tab_height

    def slide_roles(self) -> tuple[str, str, str, str]:
        """Stop wall, entry wall, and the two walls that carry the slots."""
        return {
            "back": ("wall-back", "wall-front", "wall-left", "wall-right"),
            "front": ("wall-front", "wall-back", "wall-left", "wall-right"),
            "left": ("wall-left", "wall-right", "wall-front", "wall-back"),
            "right": ("wall-right", "wall-left", "wall-front", "wall-back"),
        }[self.lid_slide]

    @property
    def finger_count(self) -> int:
        """Odd finger count along the outside height, nearest to ``finger_length``.

        Both ends of an edge stay the same kind of joint. Other edges reuse this
        spacing and may land a little long or short so their own ends still match.
        """
        height = self.height
        target = self.finger_length
        if height <= 1e-6 or target <= 1e-6:
            return 5
        raw = height / target
        limit = max(3, int(raw) + 3)
        best = 3
        best_err = abs(height / 3.0 - target)
        count = 5
        while count <= limit:
            err = abs(height / count - target)
            if err < best_err:
                best = count
                best_err = err
            count += 2
        return best

    def closed_top(self) -> bool:
        """A finger-jointed panel fills the top of the walls and does not raise the box."""
        return self.lid == "closed"

    def wall_height(self, name: str) -> float:
        """Top of a wall. A sliding lid raises the stop wall and both slotted sides.

        A latch lid raises every wall so the sheet can sit in that rim.
        """
        if self.lid == "latch":
            return self.height + 2.0 * self.thickness
        if self.lid != "slide":
            return self.height
        stop, _entry, side_a, side_b = self.slide_roles()
        if name in (stop, side_a, side_b):
            return self.height + 2.0 * self.thickness
        return self.height

    def wall_joint(self, name: str, at_start: bool) -> float | None:
        """How far the corner fingers run. None keeps the fingers the full wall height."""
        if self.lid != "slide":
            return None
        if name in ("wall-front", "wall-back"):
            partner = "wall-left" if at_start else "wall-right"
        else:
            partner = "wall-front" if at_start else "wall-back"
        return min(self.wall_height(name), self.wall_height(partner))

    def slide_span(self) -> float:
        """Installed lid length, from the outside of the entry wall to the inside of the stop."""
        along = self.outer_width if self.lid_slide in ("back", "front") else self.outer_length
        return along - self.thickness

    def slide_front_margin(self) -> float:
        """How far the drop-in opening sits back from the outside of the entry wall."""
        return 4.0 * self.thickness

    def slide_tab_length(self) -> float:
        """Requested tab length, shortened so every slot still fits on the side."""
        usable = self.slide_span() - 1.0 - self.slide_front_margin()
        cap = usable / (2.1 * self.lid_slide_count)
        return max(1.0, min(self.lid_slide_tab, cap))

    def slide_tabs(self) -> list[tuple[float, float]]:
        """Tab intervals along the slide, measured from the outside of the entry wall."""
        length = self.slide_tab_length()
        first = self.slide_front_margin() + 1.1 * length
        last = self.slide_span() - 1.0 - length
        if last < first:
            last = first
        count = self.lid_slide_count
        if count <= 1:
            starts = [first]
        else:
            step = (last - first) / (count - 1)
            starts = [first + i * step for i in range(count)]
        return [(start, start + length) for start in starts]

    def slide_finger_hole(self, kerf: float = 0.0) -> list[tuple[float, float]] | None:
        """Pull hole in box coordinates, centered on the front tab.

        A 20 mm circle with a 14 mm flat facing the front of the lid. `kerf`
        shrinks the path so a centerline cut finishes at that size.
        """
        tabs = self.slide_tabs()
        if not tabs:
            return None
        finished_r = 10.0
        half_flat = 7.0
        d_fin = math.sqrt(finished_r * finished_r - half_flat * half_flat)
        radius = finished_r - kerf / 2.0
        d_draw = d_fin - kerf / 2.0
        if radius < 4.0 or d_draw <= 0.4 or d_draw >= radius - 0.2:
            return None
        half = math.sqrt(max(0.0, radius * radius - d_draw * d_draw))
        start, end = tabs[0]
        mid_along = (start + end) / 2.0
        a0, a1 = self.slide_body_across()
        if (a1 - a0) < finished_r * 2.0 + 6.0:
            return None
        if mid_along - d_fin < 2.0 or mid_along + finished_r > self.slide_span() - 2.0:
            return None
        mid_across = (a0 + a1) / 2.0
        cx, cy = self.slide_point(mid_along, mid_across)
        front = self.slide_point(0.0, mid_across)
        ahead = self.slide_point(1.0, mid_across)
        fx, fy = front[0] - ahead[0], front[1] - ahead[1]
        flen = math.hypot(fx, fy)
        if flen < 1e-6:
            return None
        fx, fy = fx / flen, fy / flen
        px, py = -fy, fx
        theta = math.atan2(half, d_draw)
        steps = 28
        sweep = 2.0 * math.pi - 2.0 * theta
        pts: list[tuple[float, float]] = []
        for i in range(steps + 1):
            ang = theta + sweep * i / steps
            dx = math.cos(ang) * fx + math.sin(ang) * px
            dy = math.cos(ang) * fy + math.sin(ang) * py
            pts.append((cx + radius * dx, cy + radius * dy))
        area = 0.0
        for i, (x1, y1) in enumerate(pts):
            x2, y2 = pts[(i + 1) % len(pts)]
            area += x1 * y2 - x2 * y1
        if area < 0.0:
            pts.reverse()
        return pts

    def slide_point(self, along: float, across: float) -> tuple[float, float]:
        """Box point. `along` grows from the entry wall toward the stop. `across` is a box axis."""
        if self.lid_slide == "back":
            return (across, along)
        if self.lid_slide == "front":
            return (across, self.outer_width - along)
        if self.lid_slide == "left":
            return (self.outer_length - along, across)
        return (along, across)

    def slide_body_across(self) -> tuple[float, float]:
        """Inner faces of the slotted walls, on the across axis."""
        if self.lid_slide in ("back", "front"):
            return (self.thickness, self.outer_length - self.thickness)
        return (self.thickness, self.outer_width - self.thickness)

    def slide_outer_across(self) -> tuple[float, float]:
        """Outer faces of the slotted walls, on the across axis."""
        if self.lid_slide in ("back", "front"):
            return (0.0, self.outer_length)
        return (0.0, self.outer_width)

    def _latch_layout(self) -> tuple[int, float, float, float, float, float, float]:
        """Loops, drawn beam, gap, width, hole radius, hole center y, and first beam y.

        The spring is cut in the lid. Its gaps add up to at least the wall
        thickness, so a pull toward the middle can draw the tab out of the slot.
        The drawn beam includes kerf, so the wood left is the beam requested.
        """
        kerf = self.kerf
        travel = self.thickness + 1.0
        loops = max(2, self.lid_latch_loops)
        beam = self.lid_latch_beam + kerf
        count = 2 if self.lid_latch_count == 2 else 1
        across, along = self.latch_axes()
        margin = max(14.0, self.thickness + 8.0)
        between = 8.0 if count == 2 else 0.0
        usable = across - 2.0 * margin - between
        each = max(0.0, usable / count) if count else 0.0
        width = min(self.lid_latch_width, each) if each > 0 else self.lid_latch_width
        if each > 0:
            width = min(max(width, 0.0), each)
        width = max(width, 8.0)
        room = width - 2.0 * self.lid_latch_beam - 3.0
        hole_r = min(8.0, max(0.0, room / 2.0))
        if hole_r < 3.5:
            hole_r = 0.0
        gap = max(1.2, kerf + 0.5, travel / loops)
        spring = loops * (beam + gap)
        hole_block = (hole_r * 2.0 + 2.0 * beam + 2.4) if hole_r else (beam + 2.0)
        budget = max(24.0, (along - 2.0 * self.thickness) * 0.5)
        while loops > 2 and self.thickness + hole_block + spring > budget:
            loops -= 1
            gap = max(1.2, kerf + 0.5, travel / max(loops, 1))
            spring = loops * (beam + gap)
        while beam > 1.0 + kerf and self.thickness + hole_block + spring > budget:
            beam = max(1.0 + kerf, beam - 0.25)
            spring = loops * (beam + gap)
        if hole_r:
            hole_cy = self.thickness + beam + 1.2 + hole_r
            spring_y0 = hole_cy + hole_r + beam + 1.2
        else:
            hole_cy = 0.0
            spring_y0 = self.thickness + beam + 1.2
        return loops, beam, gap, width, hole_r, hole_cy, spring_y0

    def latch_axes(self) -> tuple[float, float]:
        """Outer length of the latch wall, and the outer distance across to the opposite wall."""
        if self.lid_latch_side in ("left", "right"):
            return self.outer_width, self.outer_length
        return self.outer_length, self.outer_width

    def latch_walls(self) -> tuple[str, str]:
        """Wall the spring tabs enter, and the opposite wall with the two plain tabs."""
        return {
            "front": ("wall-front", "wall-back"),
            "back": ("wall-back", "wall-front"),
            "left": ("wall-left", "wall-right"),
            "right": ("wall-right", "wall-left"),
        }[self.lid_latch_side]

    def latch_point(self, across: float, inward: float) -> tuple[float, float]:
        """Box point. `inward` grows from the outside of the latch wall toward the middle."""
        if self.lid_latch_side == "back":
            return (across, self.outer_width - inward)
        if self.lid_latch_side == "left":
            return (inward, across)
        if self.lid_latch_side == "right":
            return (self.outer_length - inward, across)
        return (across, inward)

    def latch_centers(self) -> list[float]:
        """Centers of the spring tabs, measured along the latch wall."""
        _loops, _beam, _gap, width, _hole_r, _hole_cy, _spring_y0 = self._latch_layout()
        across, _along = self.latch_axes()
        mid = across / 2.0
        if self.lid_latch_count != 2:
            return [mid]
        return [mid - (width / 2.0 + 4.0), mid + (width / 2.0 + 4.0)]

    def latch_tab_spans(self) -> list[tuple[float, float]]:
        """Intervals of the spring tabs along the latch wall."""
        _loops, _beam, _gap, width, _hole_r, _hole_cy, _spring_y0 = self._latch_layout()
        half = width / 2.0
        return [(center - half, center + half) for center in self.latch_centers()]

    def latch_finger_holes(self, kerf: float = 0.0) -> list[list[tuple[float, float]]]:
        """One hole in each latch tab, in box coordinates. `kerf` shrinks the cut."""
        _loops, _beam, _gap, _width, hole_r, hole_cy, _spring_y0 = self._latch_layout()
        radius = hole_r - kerf / 2.0
        if radius < 3.0:
            return []
        holes: list[list[tuple[float, float]]] = []
        steps = 28
        for center in self.latch_centers():
            pts = [
                self.latch_point(
                    center + radius * math.cos(2.0 * math.pi * i / steps),
                    hole_cy + radius * math.sin(2.0 * math.pi * i / steps),
                )
                for i in range(steps)
            ]
            area = 0.0
            for i, (x1, y1) in enumerate(pts):
                x2, y2 = pts[(i + 1) % len(pts)]
                area += x1 * y2 - x2 * y1
            if area < 0.0:
                pts.reverse()
            holes.append(pts)
        return holes

    def latch_back_tabs(self) -> list[tuple[float, float]]:
        """Intervals of the two plain tabs, along the wall opposite the latch."""
        across, _along = self.latch_axes()
        tab = 16.0
        inner0 = self.thickness
        inner1 = across - self.thickness
        span = inner1 - inner0
        if span < tab * 2.0 + 10.0:
            tab = max(8.0, (span - 10.0) / 2.0)
        return [
            (inner0 + span * spot - tab / 2.0, inner0 + span * spot + tab / 2.0)
            for spot in (0.28, 0.72)
        ]

    def slide_panel_x(self, along: float) -> float:
        """Position along a slotted wall's laser panel. Panel x=0 is the front or the left."""
        if self.lid_slide == "back":
            return along
        if self.lid_slide == "front":
            return self.outer_width - along
        if self.lid_slide == "right":
            return along
        return self.outer_length - along

    @property
    def outer_length(self) -> float:
        return self.length

    @property
    def outer_width(self) -> float:
        return self.width

    @property
    def inner_length(self) -> float:
        return self.outer_length - 2.0 * self.thickness

    @property
    def inner_width(self) -> float:
        return self.outer_width - 2.0 * self.thickness


def demo_params() -> InsertParams:
    """Realistic demo: 280×200×50 mm outside, with a vertical and a horizontal divider."""
    # Coordinates are insert-local (outer origin). Thickness = 3 → inner faces at 3 mm.
    return InsertParams(
        length=280.0,
        width=200.0,
        height=50.0,
        thickness=3.0,
        kerf=0.15,
        floor=True,
        finger_length=10.0,
        lid="none",
        dividers=[
            Divider(x1=93.0, y1=3.0, x2=93.0, y2=197.0, label="vertical"),
            Divider(x1=93.0, y1=100.0, x2=277.0, y2=100.0, label="horizontal"),
        ],
    )
