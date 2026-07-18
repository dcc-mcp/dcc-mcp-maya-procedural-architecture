"""Detailed residential design and Maya/Bifrost realization."""

from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

MAX_SEED = 2_147_483_647
SUPPORTED_STYLES = ("craftsman", "farmhouse", "cottage")
TEXTURE_ROLES = ("siding", "roof", "brick", "concrete")
MATERIAL_ORDER = (
    "ground",
    "concrete",
    "brick",
    "siding",
    "siding_detail",
    "roof",
    "trim",
    "glass",
    "wood",
    "metal",
    "foliage",
)
BIFROST_MATERIALS = ("ground", "concrete", "brick", "siding", "roof")
DETAIL_MATERIAL_ALIASES = {"siding_detail": "siding"}


@dataclass(frozen=True)
class Part:
    """One material-tagged procedural primitive."""

    name: str
    material: str
    dimensions: Tuple[float, float, float]
    position: Tuple[float, float, float]
    rotation_z: float = 0.0
    primitive: str = "box"


@dataclass(frozen=True)
class HouseDesign:
    """Host-independent deterministic architecture plan."""

    seed: int
    style: str
    parts: Tuple[Part, ...]


def _rounded(value: float) -> float:
    return round(float(value), 4)


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "RealisticHouse")).strip("_")
    if not name:
        name = "RealisticHouse"
    if name[0].isdigit():
        name = "House_" + name
    return name


def resolve_seed(seed: Optional[int]) -> int:
    """Validate or generate a reproducible house seed."""
    if seed is None:
        return random.SystemRandom().randint(0, MAX_SEED)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
        raise ValueError(f"seed must be an integer between 0 and {MAX_SEED}")
    return seed


def _box(
    parts: List[Part],
    name: str,
    material: str,
    dimensions: Sequence[float],
    position: Sequence[float],
    rotation_z: float = 0.0,
) -> None:
    parts.append(
        Part(
            name=name,
            material=material,
            dimensions=tuple(_rounded(value) for value in dimensions),  # type: ignore[arg-type]
            position=tuple(_rounded(value) for value in position),  # type: ignore[arg-type]
            rotation_z=_rounded(rotation_z),
        )
    )


def _ellipsoid(
    parts: List[Part],
    name: str,
    material: str,
    dimensions: Sequence[float],
    position: Sequence[float],
) -> None:
    parts.append(
        Part(
            name=name,
            material=material,
            dimensions=tuple(_rounded(value) for value in dimensions),  # type: ignore[arg-type]
            position=tuple(_rounded(value) for value in position),  # type: ignore[arg-type]
            primitive="ellipsoid",
        )
    )


def _gable_roof(
    parts: List[Part],
    name: str,
    center_x: float,
    base_y: float,
    center_z: float,
    width: float,
    height: float,
    depth: float,
) -> None:
    """Add roof planes, ridge, fascia, gutters, and end trim."""
    half_run = width / 2.0
    slope = math.sqrt(half_run**2 + height**2)
    angle = math.degrees(math.atan2(height, half_run))
    thickness = 0.22
    center_y = base_y + height / 2.0
    for side, direction in (("left", 1.0), ("right", -1.0)):
        plane_x = center_x - direction * width / 4.0
        _box(
            parts,
            f"{name}_{side}",
            "roof",
            (slope + 0.45, thickness, depth + 0.7),
            (plane_x, center_y, center_z),
            angle * direction,
        )
        for end, z_offset in (
            ("front", depth / 2.0 + 0.38),
            ("back", -depth / 2.0 - 0.38),
        ):
            _box(
                parts,
                f"{name}_{side}_fascia_{end}",
                "trim",
                (slope + 0.48, 0.19, 0.18),
                (plane_x, center_y - 0.02, center_z + z_offset),
                angle * direction,
            )
    _box(
        parts,
        name + "_ridge",
        "roof",
        (0.24, 0.25, depth + 0.9),
        (center_x, base_y + height, center_z),
    )
    for side, direction in (("left", -1.0), ("right", 1.0)):
        edge_x = center_x + direction * (width / 2.0 + 0.16)
        _box(
            parts,
            f"{name}_{side}_gutter",
            "wood",
            (0.16, 0.18, depth + 0.75),
            (edge_x, base_y, center_z),
        )


def _gable_infill(
    parts: List[Part],
    name: str,
    center_x: float,
    base_y: float,
    front_z: float,
    width: float,
    height: float,
) -> None:
    """Approximate a textured triangular gable with fine horizontal courses."""
    courses = 10
    course_height = height / courses
    for index in range(courses):
        width_at_course = width * (1.0 - (index + 0.5) / courses)
        _box(
            parts,
            f"{name}_course_{index:02d}",
            "siding_detail",
            (max(0.18, width_at_course), course_height + 0.015, 0.18),
            (center_x, base_y + (index + 0.5) * course_height, front_z),
        )


def _front_window(
    parts: List[Part],
    name: str,
    x: float,
    y: float,
    z: float,
    width: float = 1.45,
    height: float = 1.65,
) -> None:
    """Add a recessed window, four-piece casing, and divided lights."""
    depth = 0.08
    rail = 0.08
    _box(parts, name + "_recess", "metal", (width + 0.18, height + 0.18, 0.06), (x, y, z))
    _box(parts, name + "_glass", "glass", (width, height, depth), (x, y, z + 0.06))
    frame_z = z + 0.12
    _box(
        parts,
        name + "_top",
        "trim",
        (width + 0.2, rail, 0.1),
        (x, y + height / 2.0 + rail / 2.0, frame_z),
    )
    _box(
        parts,
        name + "_bottom",
        "trim",
        (width + 0.26, rail, 0.12),
        (x, y - height / 2.0 - rail / 2.0, frame_z),
    )
    _box(
        parts,
        name + "_left",
        "trim",
        (rail, height, 0.1),
        (x - width / 2.0 - rail / 2.0, y, frame_z),
    )
    _box(
        parts,
        name + "_right",
        "trim",
        (rail, height, 0.1),
        (x + width / 2.0 + rail / 2.0, y, frame_z),
    )
    _box(
        parts,
        name + "_mullion_v",
        "trim",
        (0.035, height, 0.11),
        (x, y, frame_z + 0.01),
    )
    _box(parts, name + "_mullion_h", "trim", (width, 0.035, 0.11), (x, y, frame_z + 0.01))


def _side_window(
    parts: List[Part],
    name: str,
    x: float,
    y: float,
    z: float,
    width: float = 1.45,
    height: float = 1.65,
) -> None:
    """Add the same detail to an X-facing wall."""
    rail = 0.08
    _box(parts, name + "_recess", "metal", (0.06, height + 0.18, width + 0.18), (x, y, z))
    _box(parts, name + "_glass", "glass", (0.08, height, width), (x - 0.06, y, z))
    frame_x = x - 0.12
    _box(
        parts,
        name + "_top",
        "trim",
        (0.1, rail, width + 0.2),
        (frame_x, y + height / 2.0 + rail / 2.0, z),
    )
    _box(
        parts,
        name + "_bottom",
        "trim",
        (0.12, rail, width + 0.26),
        (frame_x, y - height / 2.0 - rail / 2.0, z),
    )
    _box(
        parts,
        name + "_front",
        "trim",
        (0.1, height, rail),
        (frame_x, y, z + width / 2.0 + rail / 2.0),
    )
    _box(
        parts,
        name + "_back",
        "trim",
        (0.1, height, rail),
        (frame_x, y, z - width / 2.0 - rail / 2.0),
    )
    _box(
        parts,
        name + "_mullion_v",
        "trim",
        (0.11, height, 0.035),
        (frame_x - 0.01, y, z),
    )
    _box(parts, name + "_mullion_h", "trim", (0.11, 0.035, width), (frame_x - 0.01, y, z))


def _entry_door(parts: List[Part], x: float, wall_y: float, z: float) -> None:
    width = 1.25
    height = 2.55
    _box(
        parts,
        "entry_door",
        "wood",
        (width, height, 0.12),
        (x, wall_y + height / 2.0, z),
    )
    for side, offset in (("left", -width / 2.0 - 0.13), ("right", width / 2.0 + 0.13)):
        _box(
            parts,
            "entry_casing_" + side,
            "trim",
            (0.18, height + 0.28, 0.16),
            (x + offset, wall_y + height / 2.0, z + 0.08),
        )
    _box(
        parts,
        "entry_casing_top",
        "trim",
        (width + 0.44, 0.2, 0.16),
        (x, wall_y + height + 0.1, z + 0.08),
    )
    for row, panel_y in enumerate((wall_y + 0.55, wall_y + 1.25, wall_y + 1.95)):
        _box(
            parts,
            f"entry_panel_{row}",
            "wood",
            (0.86, 0.42, 0.035),
            (x, panel_y, z + 0.08),
        )
    _box(
        parts,
        "entry_handle",
        "metal",
        (0.07, 0.12, 0.09),
        (x + 0.42, wall_y + 1.25, z + 0.15),
    )
    _box(
        parts,
        "entry_transom",
        "glass",
        (width, 0.34, 0.08),
        (x, wall_y + height + 0.38, z + 0.05),
    )


def _garage_door(parts: List[Part], x: float, base_y: float, z: float, width: float) -> None:
    height = 2.55
    _box(
        parts,
        "garage_door",
        "wood",
        (width, height, 0.1),
        (x, base_y + height / 2.0, z),
    )
    for row in range(1, 4):
        y = base_y + row * height / 4.0
        _box(
            parts,
            f"garage_rail_{row}",
            "trim",
            (width - 0.16, 0.035, 0.035),
            (x, y, z + 0.08),
        )
    for column in range(1, 4):
        px = x - width / 2.0 + column * width / 4.0
        _box(
            parts,
            f"garage_stile_{column}",
            "trim",
            (0.035, height - 0.14, 0.035),
            (px, base_y + height / 2.0, z + 0.08),
        )
    window_y = base_y + height * 0.82
    for index in range(4):
        px = x - width * 0.375 + index * width * 0.25
        _box(
            parts,
            f"garage_window_{index}",
            "glass",
            (width * 0.19, 0.36, 0.07),
            (px, window_y, z + 0.1),
        )


def design_house(seed: Optional[int] = None, style: str = "craftsman") -> HouseDesign:
    """Return a detailed deterministic residential exterior without importing Maya."""
    resolved_seed = resolve_seed(seed)
    normalized_style = str(style).strip().lower()
    if normalized_style not in SUPPORTED_STYLES:
        raise ValueError("style must be one of: {}".format(", ".join(SUPPORTED_STYLES)))
    rng = random.Random(resolved_seed)
    presets = {
        "craftsman": {
            "main_width": (12.0, 13.1),
            "main_depth": (8.7, 9.5),
            "wall_height": (6.1, 6.6),
            "roof_height": (2.9, 3.5),
            "garage_width": (6.6, 7.3),
            "garage_depth": (8.0, 8.7),
            "wing_ratio": 0.42,
            "wing_depth": 3.0,
            "garage_wall_height": 3.2,
            "porch_width": 4.8,
        },
        "farmhouse": {
            "main_width": (13.2, 14.4),
            "main_depth": (9.1, 10.0),
            "wall_height": (6.5, 7.0),
            "roof_height": (3.8, 4.4),
            "garage_width": (7.0, 7.8),
            "garage_depth": (8.4, 9.2),
            "wing_ratio": 0.36,
            "wing_depth": 3.4,
            "garage_wall_height": 3.35,
            "porch_width": 6.4,
        },
        "cottage": {
            "main_width": (10.8, 11.9),
            "main_depth": (8.0, 8.8),
            "wall_height": (5.4, 5.9),
            "roof_height": (3.7, 4.3),
            "garage_width": (5.9, 6.5),
            "garage_depth": (7.3, 8.0),
            "wing_ratio": 0.5,
            "wing_depth": 3.2,
            "garage_wall_height": 3.0,
            "porch_width": 4.0,
        },
    }
    preset = presets[normalized_style]
    main_width = rng.uniform(*preset["main_width"])
    main_depth = rng.uniform(*preset["main_depth"])
    wall_height = rng.uniform(*preset["wall_height"])
    roof_height = rng.uniform(*preset["roof_height"])
    garage_width = rng.uniform(*preset["garage_width"])
    garage_depth = rng.uniform(*preset["garage_depth"])
    wing_width = main_width * preset["wing_ratio"]
    main_x = -1.6
    garage_x = main_x + main_width / 2.0 + garage_width / 2.0 - 1.1
    garage_z = 1.0
    wing_x = main_x - main_width * 0.25
    wing_depth = preset["wing_depth"]
    wing_z = main_depth / 2.0 + wing_depth / 2.0 - 0.3
    base_y = 0.55
    main_front = main_depth / 2.0
    wing_front = wing_z + wing_depth / 2.0
    garage_front = garage_z + garage_depth / 2.0
    parts: List[Part] = []

    _box(parts, "ground", "ground", (34.0, 0.22, 28.0), (0.5, -0.16, 0.0))
    _box(
        parts,
        "main_foundation",
        "concrete",
        (main_width + 0.35, base_y, main_depth + 0.35),
        (main_x, base_y / 2.0, 0.0),
    )
    _box(
        parts,
        "garage_foundation",
        "concrete",
        (garage_width + 0.35, base_y, garage_depth + 0.35),
        (garage_x, base_y / 2.0, garage_z),
    )
    _box(
        parts,
        "main_walls",
        "siding",
        (main_width, wall_height, main_depth),
        (main_x, base_y + wall_height / 2.0, 0.0),
    )
    _box(
        parts,
        "front_gable_volume",
        "siding",
        (wing_width, wall_height, wing_depth),
        (wing_x, base_y + wall_height / 2.0, wing_z),
    )
    garage_wall_height = preset["garage_wall_height"]
    _box(
        parts,
        "garage_walls",
        "siding",
        (garage_width, garage_wall_height, garage_depth),
        (garage_x, base_y + garage_wall_height / 2.0, garage_z),
    )

    _box(
        parts,
        "front_brick_water_table",
        "brick",
        (main_width + 0.12, 0.78, 0.22),
        (main_x, base_y + 0.39, main_front + 0.04),
    )
    _box(
        parts,
        "wing_brick_water_table",
        "brick",
        (wing_width + 0.12, 0.78, 0.22),
        (wing_x, base_y + 0.39, wing_front + 0.04),
    )
    _box(
        parts,
        "garage_brick_water_table",
        "brick",
        (garage_width + 0.12, 0.78, 0.22),
        (garage_x, base_y + 0.39, garage_front + 0.04),
    )

    _gable_roof(
        parts,
        "main_roof",
        main_x,
        base_y + wall_height,
        0.0,
        main_width + 1.1,
        roof_height,
        main_depth + 0.55,
    )
    _gable_infill(
        parts,
        "main_gable",
        main_x,
        base_y + wall_height,
        main_front + 0.06,
        main_width,
        roof_height,
    )
    _gable_roof(
        parts,
        "front_gable_roof",
        wing_x,
        base_y + wall_height,
        wing_z,
        wing_width + 0.5,
        roof_height * 0.92,
        wing_depth + 1.0,
    )
    _gable_infill(
        parts,
        "front_gable",
        wing_x,
        base_y + wall_height,
        wing_front + 0.08,
        wing_width,
        roof_height * 0.88,
    )
    _gable_roof(
        parts,
        "garage_roof",
        garage_x,
        base_y + garage_wall_height,
        garage_z,
        garage_width + 0.9,
        roof_height * 0.72,
        garage_depth + 0.45,
    )
    _gable_infill(
        parts,
        "garage_gable",
        garage_x,
        base_y + garage_wall_height,
        garage_front + 0.08,
        garage_width,
        roof_height * 0.68,
    )

    porch_x = main_x + main_width * 0.17
    porch_width = preset["porch_width"]
    porch_depth = 2.4
    porch_z = main_front + porch_depth / 2.0
    _box(
        parts,
        "porch_slab",
        "concrete",
        (porch_width + 0.5, 0.28, porch_depth),
        (porch_x, 0.14, porch_z),
    )
    for step in range(3):
        _box(
            parts,
            f"porch_step_{step}",
            "concrete",
            (porch_width * 0.62 + step * 0.45, 0.16, 0.48),
            (
                porch_x,
                0.08 + step * 0.16,
                main_front + porch_depth + 0.18 - step * 0.32,
            ),
        )
    _gable_roof(
        parts,
        "porch_roof",
        porch_x,
        3.72,
        porch_z,
        porch_width + 0.65,
        1.28,
        porch_depth + 0.6,
    )
    _gable_infill(
        parts,
        "porch_gable",
        porch_x,
        3.72,
        porch_z + porch_depth / 2.0 + 0.08,
        porch_width,
        1.15,
    )
    for index, px in enumerate((porch_x - porch_width * 0.39, porch_x + porch_width * 0.39)):
        _box(
            parts,
            f"porch_pier_{index}",
            "brick",
            (0.62, 0.82, 0.62),
            (px, 0.41, porch_z + porch_depth * 0.31),
        )
        _box(
            parts,
            f"porch_column_{index}",
            "trim",
            (0.32, 2.65, 0.32),
            (px, 2.05, porch_z + porch_depth * 0.31),
        )
    _box(
        parts,
        "porch_header",
        "trim",
        (porch_width * 0.9, 0.3, 0.3),
        (porch_x, 3.42, porch_z + porch_depth * 0.31),
    )
    for side, rail_x in (
        ("left", porch_x - porch_width * 0.39),
        ("right", porch_x + porch_width * 0.39),
    ):
        _box(
            parts,
            f"porch_rail_{side}_top",
            "trim",
            (1.15, 0.1, 0.12),
            (
                rail_x + (0.58 if side == "left" else -0.58),
                1.1,
                porch_z + porch_depth * 0.31,
            ),
        )
        for spindle in range(5):
            sx = rail_x + (0.18 + spindle * 0.2) * (1.0 if side == "left" else -1.0)
            _box(
                parts,
                f"porch_{side}_spindle_{spindle}",
                "trim",
                (0.055, 0.72, 0.055),
                (sx, 0.72, porch_z + porch_depth * 0.31),
            )

    door_x = porch_x
    _entry_door(parts, door_x, base_y, main_front + 0.08)
    _front_window(parts, "wing_window_lower", wing_x, 2.55, wing_front + 0.08, 1.75, 1.85)
    _front_window(parts, "wing_window_upper", wing_x, 5.25, wing_front + 0.08, 1.55, 1.55)
    _front_window(
        parts,
        "main_window_lower",
        main_x + main_width * 0.34,
        2.5,
        main_front + 0.08,
        1.55,
        1.75,
    )
    _front_window(
        parts,
        "main_window_upper_a",
        main_x + main_width * 0.12,
        5.15,
        main_front + 0.08,
        1.35,
        1.45,
    )
    _front_window(
        parts,
        "main_window_upper_b",
        main_x + main_width * 0.37,
        5.15,
        main_front + 0.08,
        1.35,
        1.45,
    )
    left_wall = main_x - main_width / 2.0 - 0.04
    for level, y in (("lower", 2.45), ("upper", 5.1)):
        for index, z in enumerate((-2.5, 0.4, 2.5)):
            _side_window(parts, f"left_{level}_{index}", left_wall, y, z, 1.35, 1.5)

    _garage_door(parts, garage_x, base_y, garage_front + 0.08, garage_width * 0.72)
    _box(
        parts,
        "garage_lintel",
        "trim",
        (garage_width * 0.78, 0.2, 0.18),
        (garage_x, base_y + 2.82, garage_front + 0.16),
    )
    for side, light_x in (
        ("left", garage_x - garage_width * 0.43),
        ("right", garage_x + garage_width * 0.43),
    ):
        _box(
            parts,
            f"garage_light_{side}",
            "metal",
            (0.2, 0.42, 0.18),
            (light_x, 2.5, garage_front + 0.2),
        )
        _box(
            parts,
            f"garage_light_glass_{side}",
            "glass",
            (0.13, 0.26, 0.12),
            (light_x, 2.5, garage_front + 0.32),
        )

    chimney_x = main_x - main_width * 0.34
    _box(
        parts,
        "chimney",
        "brick",
        (1.05, wall_height + roof_height * 0.76, 1.0),
        (chimney_x, (wall_height + roof_height * 0.76) / 2.0, -1.65),
    )
    _box(
        parts,
        "chimney_cap",
        "concrete",
        (1.28, 0.18, 1.22),
        (chimney_x, wall_height + roof_height * 0.76 + 0.09, -1.65),
    )

    driveway_length = 9.5
    _box(
        parts,
        "driveway",
        "concrete",
        (garage_width * 0.92, 0.12, driveway_length),
        (garage_x, -0.03, garage_front + driveway_length / 2.0),
    )
    _box(
        parts,
        "walkway",
        "concrete",
        (1.45, 0.12, 7.0),
        (porch_x, 0.0, main_front + porch_depth + 3.4),
    )
    for index, x in enumerate((main_x - main_width / 2.0 + 0.25, garage_x + garage_width / 2.0 - 0.25)):
        _box(
            parts,
            f"downspout_{index}",
            "metal",
            (0.14, 3.0, 0.14),
            (x, 1.5, main_front + 0.18),
        )
    for index, x in enumerate((door_x - 1.0, door_x + 1.0)):
        _box(
            parts,
            f"porch_light_{index}",
            "metal",
            (0.22, 0.38, 0.2),
            (x, 2.75, main_front + 0.23),
        )
        _box(
            parts,
            f"porch_light_glass_{index}",
            "glass",
            (0.15, 0.22, 0.13),
            (x, 2.75, main_front + 0.35),
        )

    shrub_positions = (
        (main_x - main_width * 0.48, wing_front + 0.58),
        (wing_x - main_width * 0.12, wing_front + 0.62),
        (wing_x + main_width * 0.16, wing_front + 0.62),
        (porch_x - porch_width * 0.58, main_front + 0.52),
        (porch_x + porch_width * 0.58, main_front + 0.5),
        (garage_x - garage_width * 0.56, garage_front + 0.45),
    )
    for shrub_index, (shrub_x, shrub_z) in enumerate(shrub_positions):
        spread = rng.uniform(0.75, 1.0)
        for lobe_index, (dx, dz, scale) in enumerate(((-0.28, 0.02, 0.78), (0.22, 0.08, 0.88), (0.0, -0.18, 1.0))):
            width = spread * scale
            height = width * rng.uniform(0.72, 0.92)
            depth = width * rng.uniform(0.78, 1.05)
            _ellipsoid(
                parts,
                f"shrub_{shrub_index}_{lobe_index}",
                "foliage",
                (width, height, depth),
                (shrub_x + dx, height / 2.0, shrub_z + dz),
            )

    return HouseDesign(seed=resolved_seed, style=normalized_style, parts=tuple(parts))


def _safe_extract_images(archive: Path, destination: Path) -> List[Path]:
    if not archive.is_file() or not zipfile.is_zipfile(str(archive)):
        raise ValueError(f"asset variant must be a readable zip archive: {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    extracted: List[Path] = []
    destination_root = str(destination.resolve())
    with zipfile.ZipFile(str(archive)) as bundle:
        for info in bundle.infolist():
            if info.is_dir() or Path(info.filename).suffix.lower() not in {
                ".jpg",
                ".jpeg",
                ".png",
                ".tif",
                ".tiff",
                ".exr",
            }:
                continue
            target = (destination / Path(info.filename).name).resolve()
            if os.path.commonpath([destination_root, str(target)]) != destination_root:
                raise ValueError("asset archive contains an unsafe path")
            with bundle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(target)
    return extracted


def _map_kind(path: Path) -> Optional[str]:
    name = path.name.lower()
    for token, kind in (
        ("_color.", "color"),
        ("_roughness.", "roughness"),
        ("_normalgl.", "normal"),
        ("_displacement.", "displacement"),
        ("_ambientocclusion.", "ao"),
        ("_opacity.", "opacity"),
        ("_metalness.", "metalness"),
    ):
        if token in name:
            return kind
    return None


def prepare_textures(material_assets: Mapping[str, Mapping[str, Any]], workspace_dir: str) -> Dict[str, Any]:
    """Extract required AssetDescriptors and write a truthful attribution manifest."""
    workspace = Path(workspace_dir).expanduser()
    if not workspace.is_absolute():
        raise ValueError("workspace_dir must be absolute")
    missing = [role for role in TEXTURE_ROLES if role not in material_assets]
    if missing:
        raise ValueError("material_assets missing roles: {}".format(", ".join(missing)))
    prepared: Dict[str, Any] = {}
    for role in TEXTURE_ROLES:
        descriptor = dict(material_assets[role])
        variants = descriptor.get("variants") or []
        attribution = descriptor.get("attribution") or {}
        if not descriptor.get("asset_id") or not variants:
            raise ValueError(f"{role} must be a valid AssetDescriptor")
        if attribution.get("license_spdx") != "CC0-1.0":
            raise ValueError(f"{role} material must use CC0-1.0")
        variant = next((item for item in variants if item.get("preferred")), variants[0])
        archive = Path(str(variant.get("local_path") or "")).expanduser()
        asset_folder = _safe_name(str(descriptor["asset_id"]).replace(":", "_"))
        images = _safe_extract_images(archive, workspace / "textures" / asset_folder)
        maps = {kind: str(path) for path in images for kind in [_map_kind(path)] if kind}
        required_maps = [kind for kind in ("color", "roughness", "normal") if kind not in maps]
        if required_maps:
            raise ValueError("{} asset missing PBR maps: {}".format(role, ", ".join(required_maps)))
        prepared[role] = {
            "asset_id": descriptor["asset_id"],
            "archive": str(archive),
            "maps": maps,
            "attribution": attribution,
        }
    workspace.mkdir(parents=True, exist_ok=True)
    manifest = workspace / "asset_attribution.json"
    manifest.write_text(json.dumps(prepared, indent=2, sort_keys=True), encoding="utf-8")
    return {"materials": prepared, "manifest": str(manifest)}


def _set_attr(cmds: Any, node: str, attribute: str, value: Any) -> None:
    plug = f"{node}.{attribute}"
    if not cmds.objExists(plug):
        return
    if isinstance(value, tuple):
        cmds.setAttr(plug, *value, type="double3")
    elif isinstance(value, str):
        cmds.setAttr(plug, value, type="string")
    else:
        cmds.setAttr(plug, value)


def _new_surface(cmds: Any, name: str) -> Tuple[str, str]:
    material = cmds.shadingNode("standardSurface", asShader=True, name=name)
    shading_group = cmds.sets(empty=True, renderable=True, noSurfaceShader=True, name=name + "SG")
    cmds.connectAttr(material + ".outColor", shading_group + ".surfaceShader", force=True)
    return material, shading_group


def _triplanar_file(
    cmds: Any,
    name: str,
    path: str,
    scale: float,
    color_space: str,
    color_gain: Optional[Tuple[float, float, float]] = None,
) -> str:
    texture = cmds.shadingNode("file", asTexture=True, name=name + "_File")
    _set_attr(cmds, texture, "fileTextureName", str(path).replace("\\", "/"))
    _set_attr(cmds, texture, "colorSpace", color_space)
    if color_gain is not None:
        _set_attr(cmds, texture, "colorGain", color_gain)
    triplanar = cmds.shadingNode("aiTriplanar", asUtility=True, name=name + "_Triplanar")
    cmds.connectAttr(texture + ".outColor", triplanar + ".input", force=True)
    _set_attr(cmds, triplanar, "coordSpace", 1)
    _set_attr(cmds, triplanar, "scale", (scale, scale, scale))
    _set_attr(cmds, triplanar, "blend", 0.25)
    return triplanar


def _pbr_surface(
    cmds: Any,
    name: str,
    maps: Mapping[str, str],
    scale: float,
    color_gain: Tuple[float, float, float],
) -> Tuple[str, str]:
    material, shading_group = _new_surface(cmds, name)
    _set_attr(cmds, material, "base", 0.9)
    _set_attr(cmds, material, "specular", 0.45)
    _set_attr(cmds, material, "coat", 0.04)
    color = _triplanar_file(cmds, name + "_Color", maps["color"], scale, "sRGB", color_gain)
    roughness = _triplanar_file(cmds, name + "_Roughness", maps["roughness"], scale, "Raw")
    normal_texture = _triplanar_file(cmds, name + "_Normal", maps["normal"], scale, "Raw")
    normal_map = cmds.shadingNode("aiNormalMap", asUtility=True, name=name + "_NormalMap")
    _set_attr(cmds, normal_map, "strength", 0.65)
    cmds.connectAttr(color + ".outColor", material + ".baseColor", force=True)
    cmds.connectAttr(roughness + ".outColorR", material + ".specularRoughness", force=True)
    cmds.connectAttr(normal_texture + ".outColor", normal_map + ".input", force=True)
    cmds.connectAttr(normal_map + ".outValue", material + ".normalCamera", force=True)
    return material, shading_group


def _solid_surface(
    cmds: Any,
    name: str,
    color: Tuple[float, float, float],
    roughness: float,
    metalness: float = 0.0,
    transmission: float = 0.0,
) -> Tuple[str, str]:
    material, shading_group = _new_surface(cmds, name)
    _set_attr(cmds, material, "baseColor", color)
    _set_attr(cmds, material, "specularRoughness", roughness)
    _set_attr(cmds, material, "metalness", metalness)
    _set_attr(cmds, material, "transmission", transmission)
    if transmission:
        _set_attr(cmds, material, "base", 0.08)
        _set_attr(cmds, material, "specular", 0.9)
        _set_attr(cmds, material, "coat", 0.15)
    return material, shading_group


def _create_materials(
    cmds: Any,
    base: str,
    prepared: Mapping[str, Any],
    style: str,
) -> Dict[str, Dict[str, str]]:
    scales = {"siding": 0.72, "roof": 0.8, "brick": 0.55, "concrete": 1.15}
    style_gains = {
        "craftsman": {
            "siding": (1.0, 1.0, 1.0),
            "roof": (1.0, 1.0, 1.0),
        },
        "farmhouse": {
            "siding": (1.65, 1.58, 1.42),
            "roof": (1.08, 1.08, 1.08),
        },
        "cottage": {
            "siding": (0.62, 0.92, 0.6),
            "roof": (0.82, 0.76, 0.68),
        },
    }
    gains = style_gains[style]
    materials: Dict[str, Dict[str, str]] = {}
    for role in TEXTURE_ROLES:
        material, shading_group = _pbr_surface(
            cmds,
            f"{base}_M_{role.title()}",
            prepared[role]["maps"],
            scales[role],
            gains.get(role, (1.0, 1.0, 1.0)),
        )
        materials[role] = {"material": material, "shading_group": shading_group}
    trim_colors = {
        "craftsman": (0.78, 0.74, 0.64),
        "farmhouse": (0.88, 0.86, 0.79),
        "cottage": (0.76, 0.68, 0.52),
    }
    solids = {
        "trim": (trim_colors[style], 0.3, 0.0, 0.0),
        "glass": ((0.025, 0.06, 0.085), 0.08, 0.0, 0.92),
        "wood": ((0.18, 0.055, 0.025), 0.26, 0.0, 0.0),
        "metal": ((0.025, 0.03, 0.035), 0.24, 0.82, 0.0),
        "ground": ((0.075, 0.16, 0.055), 0.86, 0.0, 0.0),
        "foliage": ((0.035, 0.16, 0.045), 0.72, 0.0, 0.0),
    }
    for role, values in solids.items():
        material, shading_group = _solid_surface(cmds, f"{base}_M_{role.title()}", *values)
        materials[role] = {"material": material, "shading_group": shading_group}
    return materials


def _transform_matrix(part: Part) -> Tuple[float, ...]:
    angle = math.radians(part.rotation_z)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    x, y, z = part.position
    return tuple(
        _rounded(value)
        for value in (
            cosine,
            sine,
            0.0,
            0.0,
            -sine,
            cosine,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            x,
            y,
            z,
            1.0,
        )
    )


def _build_graphs(
    cmds: Any,
    base: str,
    root: str,
    design: HouseDesign,
    materials: Mapping[str, Mapping[str, str]],
) -> Dict[str, Any]:
    from dcc_mcp_maya.bifrost import (  # noqa: PLC0415
        add_node,
        connect_ports,
        create_graph,
        create_port,
        set_port_default,
    )

    graphs: Dict[str, Dict[str, Any]] = {}
    for material_role in BIFROST_MATERIALS:
        material_parts = [part for part in design.parts if part.material == material_role]
        if not material_parts:
            continue
        record = create_graph(
            cmds,
            name=f"{base}_{material_role}_BifrostShape",
            kind="graph_shape",
        )
        graph = record["graph"]
        outputs: List[str] = []
        for index, part in enumerate(material_parts):
            node_name = f"p{index:03d}_{_safe_name(part.name)[:40]}"
            primitive = add_node(cmds, graph, "Modeling::Primitive::create_mesh_cube", name=node_name)
            width, height, depth = part.dimensions
            for port, value in (
                ("length", depth),
                ("width", width),
                ("height", height),
            ):
                set_port_default(cmds, graph, primitive, port, value)
            if abs(part.rotation_z) < 0.0001:
                set_port_default(cmds, graph, primitive, "position", part.position)
                outputs.append(f".{primitive}.cube_mesh")
            else:
                set_port_default(cmds, graph, primitive, "position", (0.0, 0.0, 0.0))
                transform = add_node(
                    cmds,
                    graph,
                    "Modeling::Points::transform_points",
                    name=node_name + "_transform",
                )
                set_port_default(cmds, graph, transform, "transform", _transform_matrix(part))
                connect_ports(
                    cmds,
                    graph,
                    f".{primitive}.cube_mesh",
                    f".{transform}.points",
                )
                outputs.append(f".{transform}.out_points")
        array_node = add_node(cmds, graph, "Core::Array::build_array", name="parts")
        for index, source in enumerate(outputs):
            port = f"part_{index:03d}"
            create_port(cmds, graph, array_node, port, "Object")
            connect_ports(cmds, graph, source, f".{array_node}.{port}")
        merge = add_node(cmds, graph, "Modeling::Common::merge_geometry", name="merge")
        connect_ports(cmds, graph, f".{array_node}.array", f".{merge}.geometry")
        create_port(cmds, graph, "output", "geometry", "Object")
        connect_ports(cmds, graph, f".{merge}.merged", ".output.geometry")
        cmds.setAttr(graph + ".displayFinalInViewport", False)
        cmds.setAttr(graph + ".displayFinalInViewport", True)
        cmds.dgdirty(graph)
        cmds.sets(graph, edit=True, forceElement=materials[material_role]["shading_group"])
        transform_name = record.get("transform")
        if transform_name:
            transform_name = cmds.parent(transform_name, root)[0]
        graphs[material_role] = {
            "graph": graph,
            "transform": transform_name,
            "part_count": len(material_parts),
        }
    return graphs


def _build_details(
    cmds: Any,
    base: str,
    root: str,
    design: HouseDesign,
    materials: Mapping[str, Mapping[str, str]],
) -> Dict[str, Any]:
    """Build repetitive finish details as fast beveled Maya render meshes."""
    detail_roles = [role for role in MATERIAL_ORDER if role not in BIFROST_MATERIALS]
    groups: Dict[str, str] = {}
    created = 0
    for role in detail_roles:
        role_parts = [part for part in design.parts if part.material == role]
        if not role_parts:
            continue
        group = cmds.group(empty=True, name=f"{base}_{role}_DETAILS", parent=root)
        groups[role] = group
        for index, part in enumerate(role_parts):
            width, height, depth = part.dimensions
            node_name = f"{base}_{role}_{index:03d}_{_safe_name(part.name)[:32]}"
            if part.primitive == "box":
                created_nodes = cmds.polyCube(
                    name=node_name,
                    width=width,
                    height=height,
                    depth=depth,
                    subdivisionsX=1,
                    subdivisionsY=1,
                    subdivisionsZ=1,
                    constructionHistory=False,
                )
            elif part.primitive == "ellipsoid":
                created_nodes = cmds.polySphere(
                    name=node_name,
                    radius=0.5,
                    subdivisionsAxis=20,
                    subdivisionsHeight=12,
                    constructionHistory=False,
                )
            else:
                raise ValueError(f"unsupported detail primitive: {part.primitive}")
            transform = created_nodes[0]
            cmds.xform(
                transform,
                worldSpace=True,
                translation=part.position,
                rotation=(0.0, 0.0, part.rotation_z),
            )
            if part.primitive == "ellipsoid":
                cmds.xform(transform, objectSpace=True, scale=part.dimensions)
            elif role != "glass":
                bevel = min(0.035, min(width, height, depth) * 0.18)
                if bevel > 0.003:
                    with suppress(RuntimeError):
                        cmds.polyBevel3(
                            transform,
                            offset=bevel,
                            segments=2,
                            offsetAsFraction=False,
                            constructionHistory=False,
                        )
            shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, fullPath=True) or []
            if not shapes:
                raise RuntimeError(f"detail mesh has no render shape: {transform}")
            material_role = DETAIL_MATERIAL_ALIASES.get(role, role)
            cmds.sets(
                shapes[0],
                edit=True,
                forceElement=materials[material_role]["shading_group"],
            )
            cmds.parent(transform, group)
            created += 1
    return {"groups": groups, "part_count": created}


def _look_at(cmds: Any, node: str, target: Tuple[float, float, float]) -> None:
    locator = cmds.spaceLocator(name=node + "_AimTarget")[0]
    cmds.xform(locator, worldSpace=True, translation=target)
    constraint = cmds.aimConstraint(locator, node, aimVector=(0, 0, -1), upVector=(0, 1, 0), worldUpType="scene")[0]
    cmds.delete(constraint, locator)


def _light_nodes(cmds: Any, node: str) -> Tuple[str, str]:
    """Normalize Maya light commands that may return a shape or transform."""
    if cmds.nodeType(node) == "transform":
        shapes = cmds.listRelatives(node, shapes=True, fullPath=True) or []
        if not shapes:
            raise RuntimeError(f"light transform has no shape: {node}")
        return node, shapes[0]
    parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
    if not parents:
        raise RuntimeError(f"light shape has no transform: {node}")
    return parents[0], node


def _stage_scene(cmds: Any, base: str, root: str, frame_count: int) -> Dict[str, Any]:
    if not cmds.pluginInfo("mtoa", query=True, loaded=True):
        cmds.loadPlugin("mtoa", quiet=True)
    camera, camera_shape = cmds.camera(name=base + "_RenderCamera")
    cmds.xform(camera, worldSpace=True, translation=(24.0, 7.6, 29.0))
    _set_attr(cmds, camera_shape, "focalLength", 50.0)
    _look_at(cmds, camera, (0.0, 3.0, 0.8))
    orbit = cmds.group(empty=True, name=base + "_CameraOrbit")
    cmds.xform(orbit, worldSpace=True, pivots=(0.0, 3.4, 0.5))
    cmds.parent(camera, orbit)
    cmds.setKeyframe(orbit, attribute="rotateY", time=1, value=-18.0)
    cmds.setKeyframe(orbit, attribute="rotateY", time=frame_count, value=342.0)
    cmds.keyTangent(orbit, attribute="rotateY", inTangentType="linear", outTangentType="linear")

    skydome_node = cmds.shadingNode("aiSkyDomeLight", asLight=True, name=base + "_SkyShape")
    skydome_transform, skydome_shape = _light_nodes(cmds, skydome_node)
    physical_sky = cmds.shadingNode("aiPhysicalSky", asUtility=True, name=base + "_PhysicalSky")
    _set_attr(cmds, physical_sky, "turbidity", 2.6)
    _set_attr(cmds, physical_sky, "groundAlbedo", (0.18, 0.2, 0.16))
    _set_attr(cmds, physical_sky, "useDegrees", True)
    _set_attr(cmds, physical_sky, "elevation", 34.0)
    _set_attr(cmds, physical_sky, "azimuth", 138.0)
    _set_attr(cmds, physical_sky, "sunSize", 1.6)
    _set_attr(cmds, physical_sky, "intensity", 1.8)
    cmds.connectAttr(physical_sky + ".outColor", skydome_shape + ".color", force=True)
    _set_attr(cmds, skydome_shape, "intensity", 1.0)

    cmds.parent(orbit, skydome_transform, root)
    _set_attr(cmds, "defaultRenderGlobals", "currentRenderer", "arnold")
    _set_attr(cmds, "defaultResolution", "width", 1280)
    _set_attr(cmds, "defaultResolution", "height", 720)
    _set_attr(cmds, "defaultResolution", "deviceAspectRatio", 16.0 / 9.0)
    _set_attr(cmds, "defaultRenderGlobals", "startFrame", 1.0)
    _set_attr(cmds, "defaultRenderGlobals", "endFrame", float(frame_count))
    _set_attr(cmds, "defaultArnoldRenderOptions", "AASamples", 5)
    _set_attr(cmds, "defaultArnoldRenderOptions", "GIDiffuseSamples", 2)
    _set_attr(cmds, "defaultArnoldRenderOptions", "GISpecularSamples", 2)
    _set_attr(cmds, "defaultArnoldRenderOptions", "GITransmissionSamples", 2)
    cmds.currentTime(1, edit=True)
    if not cmds.about(batch=True):
        cmds.lookThru(camera)
    return {
        "camera": camera,
        "camera_shape": camera_shape,
        "camera_orbit": orbit,
        "frame_range": [1, frame_count],
        "renderer": "arnold",
        "resolution": [1280, 720],
        "lighting": {"skydome": skydome_shape, "physical_sky": physical_sky},
    }


def generate_house(
    cmds: Any,
    material_assets: Mapping[str, Mapping[str, Any]],
    workspace_dir: str,
    seed: Optional[int] = None,
    style: str = "craftsman",
    name: str = "RealisticHouse",
    replace: bool = True,
    frame_count: int = 96,
) -> Dict[str, Any]:
    """Create geometry, Arnold look-dev, lighting, and camera in the current scene."""
    if not 24 <= int(frame_count) <= 240:
        raise ValueError("frame_count must be between 24 and 240")
    if not cmds.pluginInfo("mayaVnnPlugin", query=True, loaded=True):
        cmds.loadPlugin("mayaVnnPlugin", quiet=True)
    if not cmds.pluginInfo("bifrostGraph", query=True, loaded=True):
        cmds.loadPlugin("bifrostGraph", quiet=True)
    if not cmds.pluginInfo("mtoa", query=True, loaded=True):
        cmds.loadPlugin("mtoa", quiet=True)
    base = _safe_name(name)
    root_name = base + "_ROOT"
    if cmds.objExists(root_name):
        if not replace:
            raise ValueError(f"{root_name} already exists; pass replace=true")
        cmds.delete(root_name)
    for node in cmds.ls(base + "_M_*", base + "_M_*SG", base + "_PhysicalSky") or []:
        if cmds.objExists(node):
            cmds.delete(node)

    texture_context = prepare_textures(material_assets, workspace_dir)
    design = design_house(seed=seed, style=style)
    root = cmds.group(empty=True, name=root_name)
    materials = _create_materials(cmds, base, texture_context["materials"], design.style)
    graphs = _build_graphs(cmds, base, root, design, materials)
    details = _build_details(cmds, base, root, design, materials)
    bounds = [float(value) for value in cmds.exactWorldBoundingBox(root)]
    staging = _stage_scene(cmds, base, root, int(frame_count))
    cmds.select(root, replace=True)
    cmds.refresh(force=True)
    return {
        "name": base,
        "root": root,
        "style": design.style,
        "seed": design.seed,
        "part_count": len(design.parts),
        "graphs": graphs,
        "details": details,
        "materials": materials,
        "bounds": bounds,
        "texture_manifest": texture_context["manifest"],
        "texture_assets": texture_context["materials"],
        **staging,
    }


_DIALOGS: List[Any] = []


def show_generator_dialog(
    material_assets: Mapping[str, Mapping[str, Any]],
    workspace_dir: str,
    name: str = "RealisticHouse",
    seed: Optional[int] = None,
    style: str = "craftsman",
) -> Dict[str, Any]:
    """Open a compact PySide generator that reuses the standalone contract."""
    import maya.cmds as cmds  # noqa: PLC0415

    if cmds.about(batch=True):
        raise RuntimeError("show_house_generator requires interactive Maya; use generate_realistic_house in standalone")
    normalized_style = str(style).strip().lower()
    if normalized_style not in SUPPORTED_STYLES:
        raise ValueError("style must be one of: {}".format(", ".join(SUPPORTED_STYLES)))
    try:
        from PySide6 import QtCore, QtWidgets  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        from PySide2 import QtCore, QtWidgets  # type: ignore[import-not-found,no-redef]  # noqa: PLC0415

    class HouseGeneratorDialog(QtWidgets.QDialog):
        def __init__(self) -> None:
            super().__init__(QtWidgets.QApplication.activeWindow())
            self.setWindowTitle("Realistic Bifrost House Generator")
            self.setObjectName("dccMcpRealisticHouseGenerator")
            self.setMinimumWidth(430)
            layout = QtWidgets.QVBoxLayout(self)
            form = QtWidgets.QFormLayout()
            self.name_edit = QtWidgets.QLineEdit(name)
            self.seed_spin = QtWidgets.QSpinBox()
            self.seed_spin.setRange(0, MAX_SEED)
            self.seed_spin.setValue(resolve_seed(seed))
            self.style_combo = QtWidgets.QComboBox()
            self.style_combo.addItems(list(SUPPORTED_STYLES))
            self.style_combo.setCurrentText(normalized_style)
            form.addRow("House name", self.name_edit)
            form.addRow("Seed", self.seed_spin)
            form.addRow("Style", self.style_combo)
            layout.addLayout(form)
            assets_label = QtWidgets.QLabel(
                "PBR: "
                + ", ".join("{}={}".format(role, material_assets[role].get("asset_id")) for role in TEXTURE_ROLES)
            )
            assets_label.setWordWrap(True)
            layout.addWidget(assets_label)
            self.status = QtWidgets.QLabel("Ready")
            layout.addWidget(self.status)
            buttons = QtWidgets.QHBoxLayout()
            generate_button = QtWidgets.QPushButton("Generate")
            random_button = QtWidgets.QPushButton("Randomize")
            close_button = QtWidgets.QPushButton("Close")
            buttons.addWidget(generate_button)
            buttons.addWidget(random_button)
            buttons.addStretch(1)
            buttons.addWidget(close_button)
            layout.addLayout(buttons)
            generate_button.clicked.connect(self.generate)
            random_button.clicked.connect(self.randomize)
            close_button.clicked.connect(self.close)

        @QtCore.Slot()
        def randomize(self) -> None:
            system_random = random.SystemRandom()
            self.seed_spin.setValue(system_random.randint(0, MAX_SEED))
            self.style_combo.setCurrentIndex(system_random.randrange(len(SUPPORTED_STYLES)))
            self.generate()

        @QtCore.Slot()
        def generate(self) -> None:
            self.status.setText("Building Bifrost graphs and Arnold materials...")
            QtWidgets.QApplication.processEvents()
            try:
                result = generate_house(
                    cmds,
                    material_assets=material_assets,
                    workspace_dir=workspace_dir,
                    seed=self.seed_spin.value(),
                    style=self.style_combo.currentText(),
                    name=self.name_edit.text(),
                    replace=True,
                )
                for panel in cmds.getPanel(type="modelPanel") or []:
                    cmds.modelPanel(panel, edit=True, camera=result["camera"])
                cmds.refresh(force=True)
                self.status.setText(
                    "{} · seed {} · {} detailed parts".format(
                        result["style"],
                        result["seed"],
                        result["part_count"],
                    )
                )
            except Exception as exc:  # pragma: no cover - Maya UI path
                self.status.setText(f"Failed: {exc}")

    for dialog in list(_DIALOGS):
        with suppress(RuntimeError):
            dialog.close()
    dialog = HouseGeneratorDialog()
    _DIALOGS[:] = [dialog]
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return {
        "dialog": dialog.objectName(),
        "seed": dialog.seed_spin.value(),
        "style": dialog.style_combo.currentText(),
        "mode": "interactive_qt",
    }
