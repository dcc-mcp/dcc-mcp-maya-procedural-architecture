"""Detailed residential design and Maya/Bifrost realization."""

from __future__ import annotations

import json
import math
import os
import random
import re
import shutil
import zipfile
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

MAX_SEED = 2_147_483_647
MAX_GENERATED_PARTS = 420
SUPPORTED_STYLES = ("craftsman", "farmhouse", "cottage", "tudor", "coastal", "modern_farmhouse")
SUPPORTED_LOOKS = ("realistic", "stylized")
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
    features: Tuple[str, ...] = ()


ProgressCallback = Callable[[int, str], None]


class GenerationCancelled(RuntimeError):
    """Raised when the interactive user cancels a generation pass."""


def _emit_progress(progress: Optional[ProgressCallback], value: int, message: str) -> None:
    if progress is not None:
        progress(max(0, min(100, int(value))), str(message))


@contextmanager
def _maya_generation_guard(cmds: Any) -> Iterator[None]:
    """Reduce Maya evaluation pressure and restore host state on every exit path."""
    undo_enabled = bool(cmds.undoInfo(query=True, state=True))
    auto_key_enabled = bool(cmds.autoKeyframe(query=True, state=True))
    cmds.refresh(suspend=True)
    if undo_enabled:
        cmds.undoInfo(stateWithoutFlush=False)
    if auto_key_enabled:
        cmds.autoKeyframe(state=False)
    try:
        yield
    finally:
        if auto_key_enabled:
            cmds.autoKeyframe(state=True)
        if undo_enabled:
            cmds.undoInfo(stateWithoutFlush=True)
        cmds.refresh(suspend=False)


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
            "main_width": (11.8, 14.2),
            "main_depth": (8.4, 10.2),
            "wall_height": (5.9, 6.9),
            "roof_height": (2.8, 3.8),
            "garage_width": (6.2, 8.0),
            "garage_depth": (7.7, 9.3),
            "wing_ratio": (0.34, 0.5),
            "wing_depth": (2.7, 3.8),
            "garage_wall_height": (3.0, 3.55),
            "porch_width": (4.2, 6.4),
            "porch_depth": (2.1, 3.0),
            "dormers": (0, 2),
        },
        "farmhouse": {
            "main_width": (12.8, 15.8),
            "main_depth": (8.8, 10.8),
            "wall_height": (6.3, 7.4),
            "roof_height": (3.6, 4.8),
            "garage_width": (6.7, 8.6),
            "garage_depth": (8.0, 9.8),
            "wing_ratio": (0.3, 0.44),
            "wing_depth": (3.0, 4.2),
            "garage_wall_height": (3.15, 3.7),
            "porch_width": (5.8, 8.8),
            "porch_depth": (2.3, 3.3),
            "dormers": (1, 3),
        },
        "cottage": {
            "main_width": (9.8, 12.6),
            "main_depth": (7.4, 9.4),
            "wall_height": (5.1, 6.2),
            "roof_height": (3.4, 4.7),
            "garage_width": (5.5, 7.0),
            "garage_depth": (7.0, 8.6),
            "wing_ratio": (0.42, 0.58),
            "wing_depth": (2.8, 4.0),
            "garage_wall_height": (2.85, 3.35),
            "porch_width": (3.4, 5.2),
            "porch_depth": (1.9, 2.8),
            "dormers": (0, 1),
        },
        "tudor": {
            "main_width": (11.6, 14.0),
            "main_depth": (8.4, 10.4),
            "wall_height": (6.2, 7.3),
            "roof_height": (4.2, 5.4),
            "garage_width": (6.0, 7.8),
            "garage_depth": (7.6, 9.2),
            "wing_ratio": (0.38, 0.54),
            "wing_depth": (3.1, 4.4),
            "garage_wall_height": (3.0, 3.55),
            "porch_width": (3.2, 5.0),
            "porch_depth": (1.8, 2.6),
            "dormers": (1, 2),
        },
        "coastal": {
            "main_width": (12.4, 15.6),
            "main_depth": (8.2, 10.7),
            "wall_height": (6.2, 7.5),
            "roof_height": (3.1, 4.3),
            "garage_width": (6.4, 8.4),
            "garage_depth": (7.7, 9.6),
            "wing_ratio": (0.3, 0.46),
            "wing_depth": (2.9, 4.2),
            "garage_wall_height": (3.1, 3.7),
            "porch_width": (6.2, 9.4),
            "porch_depth": (2.5, 3.5),
            "dormers": (1, 3),
        },
        "modern_farmhouse": {
            "main_width": (13.0, 16.4),
            "main_depth": (8.8, 11.2),
            "wall_height": (6.4, 7.6),
            "roof_height": (3.8, 5.1),
            "garage_width": (7.0, 9.2),
            "garage_depth": (8.1, 10.0),
            "wing_ratio": (0.28, 0.44),
            "wing_depth": (3.0, 4.5),
            "garage_wall_height": (3.2, 3.85),
            "porch_width": (5.0, 8.2),
            "porch_depth": (2.2, 3.3),
            "dormers": (0, 2),
        },
    }
    preset = presets[normalized_style]
    main_width = rng.uniform(*preset["main_width"])
    main_depth = rng.uniform(*preset["main_depth"])
    wall_height = rng.uniform(*preset["wall_height"])
    roof_height = rng.uniform(*preset["roof_height"])
    garage_width = rng.uniform(*preset["garage_width"])
    garage_depth = rng.uniform(*preset["garage_depth"])
    wing_width = main_width * rng.uniform(*preset["wing_ratio"])
    main_x = rng.uniform(-2.0, -1.1)
    garage_x = main_x + main_width / 2.0 + garage_width / 2.0 - 1.1
    garage_z = rng.uniform(0.4, 1.6)
    wing_x = main_x - main_width * rng.uniform(0.18, 0.32)
    wing_depth = rng.uniform(*preset["wing_depth"])
    wing_z = main_depth / 2.0 + wing_depth / 2.0 - rng.uniform(0.15, 0.65)
    base_y = rng.uniform(0.45, 0.68)
    main_front = main_depth / 2.0
    wing_front = wing_z + wing_depth / 2.0
    garage_front = garage_z + garage_depth / 2.0
    parts: List[Part] = []
    features = [f"palette_{resolved_seed % 3 + 1}"]

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
    garage_wall_height = rng.uniform(*preset["garage_wall_height"])
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

    dormer_count = rng.randint(*preset["dormers"])
    if dormer_count:
        features.append(f"{dormer_count}_dormers")
        dormer_width = min(2.05, main_width / (dormer_count + 2.2))
        dormer_depth = rng.uniform(1.45, 1.9)
        dormer_height = rng.uniform(1.25, 1.65)
        dormer_y = base_y + wall_height + roof_height * rng.uniform(0.26, 0.38)
        span = main_width * 0.46
        for dormer_index in range(dormer_count):
            fraction = (dormer_index + 1) / float(dormer_count + 1)
            dormer_x = main_x - span / 2.0 + span * fraction
            dormer_z = main_front - dormer_depth * 0.32
            _box(
                parts,
                f"dormer_{dormer_index}_walls",
                "siding",
                (dormer_width, dormer_height, dormer_depth),
                (dormer_x, dormer_y + dormer_height / 2.0, dormer_z),
            )
            _gable_roof(
                parts,
                f"dormer_{dormer_index}_roof",
                dormer_x,
                dormer_y + dormer_height,
                dormer_z,
                dormer_width + 0.42,
                dormer_height * 0.66,
                dormer_depth + 0.5,
            )
            _gable_infill(
                parts,
                f"dormer_{dormer_index}_gable",
                dormer_x,
                dormer_y + dormer_height,
                dormer_z + dormer_depth / 2.0 + 0.08,
                dormer_width,
                dormer_height * 0.58,
            )
            _front_window(
                parts,
                f"dormer_{dormer_index}_window",
                dormer_x,
                dormer_y + dormer_height * 0.53,
                dormer_z + dormer_depth / 2.0 + 0.11,
                dormer_width * 0.54,
                dormer_height * 0.58,
            )

    porch_x = main_x + main_width * rng.uniform(0.1, 0.24)
    porch_width = rng.uniform(*preset["porch_width"])
    porch_depth = rng.uniform(*preset["porch_depth"])
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

    shrub_positions = [
        (main_x - main_width * 0.48, wing_front + 0.58),
        (wing_x - main_width * 0.12, wing_front + 0.62),
        (wing_x + main_width * 0.16, wing_front + 0.62),
        (porch_x - porch_width * 0.58, main_front + 0.52),
        (porch_x + porch_width * 0.58, main_front + 0.5),
        (garage_x - garage_width * 0.56, garage_front + 0.45),
    ]
    for _ in range(rng.randint(0, 4)):
        shrub_positions.append(
            (
                rng.uniform(main_x - main_width * 0.52, garage_x + garage_width * 0.48),
                rng.uniform(main_front + 0.35, max(main_front, garage_front) + 0.95),
            )
        )
    features.append(f"{len(shrub_positions)}_landscape_clusters")
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

    if rng.random() < 0.5:
        parts = [
            Part(
                name=part.name,
                material=part.material,
                dimensions=part.dimensions,
                position=(-part.position[0], part.position[1], part.position[2]),
                rotation_z=-part.rotation_z,
                primitive=part.primitive,
            )
            for part in parts
        ]
        features.append("garage_left")
    else:
        features.append("garage_right")
    if len(parts) > MAX_GENERATED_PARTS:
        raise RuntimeError(f"generated design exceeds the safe limit of {MAX_GENERATED_PARTS} parts")
    return HouseDesign(
        seed=resolved_seed,
        style=normalized_style,
        parts=tuple(parts),
        features=tuple(features),
    )


def _safe_extract_images(archive: Path, destination: Path) -> List[Path]:
    if not archive.is_file() or not zipfile.is_zipfile(str(archive)):
        raise ValueError(f"asset variant must be a readable zip archive: {archive}")
    destination.mkdir(parents=True, exist_ok=True)
    extracted: List[Path] = []
    destination_root = str(destination.resolve())
    with zipfile.ZipFile(str(archive)) as bundle:
        for info in bundle.infolist():
            if info.is_dir() or Path(info.filename).suffix.lower() not in {
                ".hdr",
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


def _prepare_environment_asset(
    environment_asset: Mapping[str, Any],
    workspace: Path,
) -> Dict[str, Any]:
    descriptor = dict(environment_asset)
    variants = descriptor.get("variants") or []
    attribution = descriptor.get("attribution") or {}
    if not descriptor.get("asset_id") or not variants:
        raise ValueError("environment_asset must be a valid AssetDescriptor")
    if attribution.get("license_spdx") != "CC0-1.0":
        raise ValueError("environment HDR must use CC0-1.0")
    variant = next((item for item in variants if item.get("preferred")), variants[0])
    archive = Path(str(variant.get("local_path") or "")).expanduser()
    asset_folder = _safe_name(str(descriptor["asset_id"]).replace(":", "_"))
    images = _safe_extract_images(archive, workspace / "environment" / asset_folder)
    candidates = [path for path in images if path.suffix.lower() in {".exr", ".hdr", ".tif", ".tiff"}]
    if not candidates:
        raise ValueError("environment_asset archive must contain an EXR, HDR, or TIFF image")
    environment_path = max(candidates, key=lambda path: (path.suffix.lower() == ".exr", path.stat().st_size))
    return {
        "asset_id": descriptor["asset_id"],
        "archive": str(archive),
        "path": str(environment_path),
        "attribution": attribution,
    }


def prepare_textures(
    material_assets: Mapping[str, Mapping[str, Any]],
    workspace_dir: str,
    environment_asset: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract CC0 material/HDR descriptors and write a truthful attribution manifest."""
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
    prepared_environment = (
        _prepare_environment_asset(environment_asset, workspace) if environment_asset is not None else None
    )
    workspace.mkdir(parents=True, exist_ok=True)
    manifest = workspace / "asset_attribution.json"
    manifest_data = dict(prepared)
    if prepared_environment is not None:
        manifest_data["environment"] = prepared_environment
    manifest.write_text(json.dumps(manifest_data, indent=2, sort_keys=True), encoding="utf-8")
    return {"materials": prepared, "environment": prepared_environment, "manifest": str(manifest)}


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
    scalar: bool = False,
) -> str:
    texture = cmds.shadingNode("file", asTexture=True, name=name + "_File")
    _set_attr(cmds, texture, "fileTextureName", str(path).replace("\\", "/"))
    _set_attr(cmds, texture, "ignoreColorSpaceFileRules", True)
    _set_attr(cmds, texture, "colorSpace", color_space)
    if scalar:
        _set_attr(cmds, texture, "alphaIsLuminance", True)
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
    role: str,
    look: str,
) -> Tuple[str, str]:
    material, shading_group = _new_surface(cmds, name)
    realistic = look == "realistic"
    _set_attr(cmds, material, "base", 0.82 if realistic else 0.94)
    _set_attr(cmds, material, "specular", 0.5 if realistic else 0.32)
    _set_attr(cmds, material, "specularIOR", 1.5 if realistic else 1.38)
    _set_attr(cmds, material, "coat", 0.015 if realistic else 0.06)
    _set_attr(cmds, material, "coatRoughness", 0.32 if realistic else 0.5)
    color = _triplanar_file(cmds, name + "_Color", maps["color"], scale, "sRGB", color_gain)
    roughness = _triplanar_file(cmds, name + "_Roughness", maps["roughness"], scale, "Raw", scalar=True)
    normal_texture = _triplanar_file(cmds, name + "_Normal", maps["normal"], scale, "Raw")
    normal_map = cmds.shadingNode("aiNormalMap", asUtility=True, name=name + "_NormalMap")
    normal_strengths = {"siding": 0.42, "roof": 0.58, "brick": 0.72, "concrete": 0.38}
    _set_attr(cmds, normal_map, "strength", normal_strengths[role] if realistic else 0.24)
    color_output = color + ".outColor"
    if realistic and "ao" in maps:
        ao = _triplanar_file(cmds, name + "_AO", maps["ao"], scale, "Raw", scalar=True)
        multiply = cmds.shadingNode("multiplyDivide", asUtility=True, name=name + "_ColorAO")
        cmds.connectAttr(color_output, multiply + ".input1", force=True)
        cmds.connectAttr(ao + ".outColor", multiply + ".input2", force=True)
        color_output = multiply + ".output"
    cmds.connectAttr(color_output, material + ".baseColor", force=True)
    cmds.connectAttr(roughness + ".outColorR", material + ".specularRoughness", force=True)
    cmds.connectAttr(normal_texture + ".outColor", normal_map + ".input", force=True)
    normal_output = normal_map + ".outValue"
    if realistic and "displacement" in maps:
        height = _triplanar_file(
            cmds,
            name + "_Height",
            maps["displacement"],
            scale,
            "Raw",
            scalar=True,
        )
        bump = cmds.shadingNode("aiBump2d", asUtility=True, name=name + "_MicroBump")
        bump_heights = {"siding": 0.08, "roof": 0.16, "brick": 0.12, "concrete": 0.06}
        _set_attr(cmds, bump, "bumpHeight", bump_heights[role])
        cmds.connectAttr(height + ".outColorR", bump + ".bumpMap", force=True)
        cmds.connectAttr(normal_output, bump + ".normal", force=True)
        normal_output = bump + ".outValue"
    cmds.connectAttr(normal_output, material + ".normalCamera", force=True)
    if "metalness" in maps:
        metalness = _triplanar_file(
            cmds,
            name + "_Metalness",
            maps["metalness"],
            scale,
            "Raw",
            scalar=True,
        )
        cmds.connectAttr(metalness + ".outColorR", material + ".metalness", force=True)
    if "opacity" in maps:
        opacity = _triplanar_file(cmds, name + "_Opacity", maps["opacity"], scale, "Raw", scalar=True)
        cmds.connectAttr(opacity + ".outColor", material + ".opacity", force=True)
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
        _set_attr(cmds, material, "base", 0.0)
        _set_attr(cmds, material, "specular", 1.0)
        _set_attr(cmds, material, "specularIOR", 1.52)
        _set_attr(cmds, material, "thinWalled", True)
        _set_attr(cmds, material, "coat", 0.04)
    return material, shading_group


def _create_materials(
    cmds: Any,
    base: str,
    prepared: Mapping[str, Any],
    design: HouseDesign,
    look: str,
) -> Dict[str, Dict[str, str]]:
    scales = {"siding": 0.72, "roof": 0.8, "brick": 0.55, "concrete": 1.15}
    realistic_gains = {
        "craftsman": {"siding": (0.82, 0.86, 0.78), "roof": (0.82, 0.82, 0.82)},
        "farmhouse": {"siding": (1.08, 1.06, 1.0), "roof": (0.86, 0.86, 0.88)},
        "cottage": {"siding": (0.8, 0.9, 0.78), "roof": (0.8, 0.77, 0.73)},
        "tudor": {"siding": (0.76, 0.7, 0.64), "roof": (0.72, 0.72, 0.72)},
        "coastal": {"siding": (0.92, 1.0, 1.04), "roof": (0.84, 0.88, 0.92)},
        "modern_farmhouse": {"siding": (1.1, 1.08, 1.02), "roof": (0.68, 0.7, 0.74)},
    }
    stylized_gains = {
        style: {role: tuple(min(1.8, channel * 1.22) for channel in value) for role, value in roles.items()}
        for style, roles in realistic_gains.items()
    }
    style_gains = realistic_gains if look == "realistic" else stylized_gains
    palette_tints = (
        ((0.96, 0.98, 1.04), (1.0, 1.0, 1.0), (1.04, 0.98, 0.94))
        if look == "realistic"
        else ((0.82, 0.94, 1.18), (1.0, 1.0, 1.0), (1.2, 0.9, 0.72))
    )
    tint = palette_tints[design.seed % len(palette_tints)]
    gains = {
        role: tuple(_rounded(min(2.0, channel * tint[index])) for index, channel in enumerate(value))
        for role, value in style_gains[design.style].items()
    }
    materials: Dict[str, Dict[str, str]] = {}
    for role in TEXTURE_ROLES:
        material, shading_group = _pbr_surface(
            cmds,
            f"{base}_M_{role.title()}",
            prepared[role]["maps"],
            scales[role],
            gains.get(role, (1.0, 1.0, 1.0)),
            role,
            look,
        )
        materials[role] = {"material": material, "shading_group": shading_group}
    trim_colors = {
        "craftsman": (0.78, 0.74, 0.64),
        "farmhouse": (0.88, 0.86, 0.79),
        "cottage": (0.76, 0.68, 0.52),
        "tudor": (0.82, 0.76, 0.62),
        "coastal": (0.9, 0.91, 0.86),
        "modern_farmhouse": (0.12, 0.13, 0.14),
    }
    trim_color = tuple(
        _rounded(min(1.0, channel * tint[index])) for index, channel in enumerate(trim_colors[design.style])
    )
    if look == "realistic":
        solids = {
            "trim": (trim_color, 0.38, 0.0, 0.0),
            "glass": ((0.86, 0.93, 0.97), 0.06, 0.0, 0.96),
            "wood": ((0.11, 0.045, 0.022), 0.36, 0.0, 0.0),
            "metal": ((0.12, 0.13, 0.14), 0.2, 0.88, 0.0),
            "ground": ((0.055, 0.105, 0.042), 0.92, 0.0, 0.0),
            "foliage": ((0.045, 0.12, 0.038), 0.78, 0.0, 0.0),
        }
    else:
        solids = {
            "trim": (trim_color, 0.48, 0.0, 0.0),
            "glass": ((0.08, 0.28, 0.42), 0.2, 0.0, 0.62),
            "wood": ((0.32, 0.085, 0.025), 0.5, 0.0, 0.0),
            "metal": ((0.035, 0.045, 0.06), 0.38, 0.72, 0.0),
            "ground": ((0.08, 0.24, 0.055), 0.95, 0.0, 0.0),
            "foliage": ((0.04, 0.28, 0.06), 0.88, 0.0, 0.0),
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
    progress: Optional[ProgressCallback] = None,
    progress_range: Tuple[int, int] = (35, 64),
) -> Dict[str, Any]:
    from dcc_mcp_maya.bifrost import (  # noqa: PLC0415
        add_node,
        connect_ports,
        create_graph,
        create_port,
        set_port_default,
    )

    graphs: Dict[str, Dict[str, Any]] = {}
    total_parts = sum(1 for part in design.parts if part.material in BIFROST_MATERIALS)
    completed_parts = 0
    progress_start, progress_end = progress_range
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
            completed_parts += 1
            if completed_parts == total_parts or completed_parts % 4 == 0:
                fraction = completed_parts / float(max(1, total_parts))
                value = progress_start + round((progress_end - progress_start) * fraction)
                _emit_progress(
                    progress,
                    value,
                    f"Building Bifrost structure ({completed_parts}/{total_parts})",
                )
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
    progress: Optional[ProgressCallback] = None,
    progress_range: Tuple[int, int] = (65, 88),
) -> Dict[str, Any]:
    """Build repetitive finish details with shared meshes to bound host memory."""
    detail_roles = [role for role in MATERIAL_ORDER if role not in BIFROST_MATERIALS]
    groups: Dict[str, str] = {}
    created = 0
    unique_meshes = 0
    total_parts = sum(1 for part in design.parts if part.material in detail_roles)
    progress_start, progress_end = progress_range
    for role in detail_roles:
        role_parts = [part for part in design.parts if part.material == role]
        if not role_parts:
            continue
        group = cmds.group(empty=True, name=f"{base}_{role}_DETAILS", parent=root)
        groups[role] = group
        prototypes: Dict[str, str] = {}
        for index, part in enumerate(role_parts):
            node_name = f"{base}_{role}_{index:03d}_{_safe_name(part.name)[:32]}"
            prototype = prototypes.get(part.primitive)
            if prototype is None:
                prototype_name = f"{base}_{role}_{part.primitive}_PROTOTYPE"
                if part.primitive == "box":
                    prototype = cmds.polyCube(
                        name=prototype_name,
                        width=1.0,
                        height=1.0,
                        depth=1.0,
                        subdivisionsX=1,
                        subdivisionsY=1,
                        subdivisionsZ=1,
                        constructionHistory=False,
                    )[0]
                    if role != "glass":
                        with suppress(RuntimeError):
                            cmds.polyBevel3(
                                prototype,
                                offset=0.025,
                                segments=2,
                                offsetAsFraction=True,
                                constructionHistory=False,
                            )
                elif part.primitive == "ellipsoid":
                    prototype = cmds.polySphere(
                        name=prototype_name,
                        radius=0.5,
                        subdivisionsAxis=16,
                        subdivisionsHeight=10,
                        constructionHistory=False,
                    )[0]
                else:
                    raise ValueError(f"unsupported detail primitive: {part.primitive}")
                prototype = cmds.parent(prototype, group)[0]
                shapes = cmds.listRelatives(prototype, shapes=True, noIntermediate=True, fullPath=True) or []
                if not shapes:
                    raise RuntimeError(f"detail prototype has no render shape: {prototype}")
                material_role = DETAIL_MATERIAL_ALIASES.get(role, role)
                cmds.sets(
                    shapes[0],
                    edit=True,
                    forceElement=materials[material_role]["shading_group"],
                )
                prototypes[part.primitive] = prototype
                unique_meshes += 1
            transform = cmds.instance(prototype, name=node_name)[0]
            cmds.xform(
                transform,
                worldSpace=True,
                translation=part.position,
                rotation=(0.0, 0.0, part.rotation_z),
            )
            cmds.xform(transform, objectSpace=True, scale=part.dimensions)
            created += 1
            if created == total_parts or created % 8 == 0:
                fraction = created / float(max(1, total_parts))
                value = progress_start + round((progress_end - progress_start) * fraction)
                _emit_progress(
                    progress,
                    value,
                    f"Instancing architectural details ({created}/{total_parts})",
                )
        for prototype in prototypes.values():
            if cmds.objExists(prototype):
                cmds.setAttr(prototype + ".visibility", False)
    return {
        "groups": groups,
        "part_count": created,
        "unique_mesh_count": unique_meshes,
        "instanced": True,
    }


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


def _select_render_camera(cmds: Any, camera_shape: str) -> None:
    """Make the staged camera the only camera used by batch rendering."""
    for shape in cmds.ls(type="camera") or []:
        cmds.setAttr(shape + ".renderable", shape == camera_shape)


def _stage_scene(
    cmds: Any,
    base: str,
    root: str,
    frame_count: int,
    look: str,
    environment: Optional[Mapping[str, Any]] = None,
    environment_rotation: float = 0.0,
    environment_exposure: float = 0.0,
) -> Dict[str, Any]:
    if not cmds.pluginInfo("mtoa", query=True, loaded=True):
        cmds.loadPlugin("mtoa", quiet=True)
    camera, camera_shape = cmds.camera(name=base + "_RenderCamera")
    cmds.xform(camera, worldSpace=True, translation=(24.0, 7.6, 29.0))
    _set_attr(cmds, camera_shape, "focalLength", 50.0)
    _select_render_camera(cmds, camera_shape)
    _look_at(cmds, camera, (0.0, 3.0, 0.8))
    orbit = cmds.group(empty=True, name=base + "_CameraOrbit")
    cmds.xform(orbit, worldSpace=True, pivots=(0.0, 3.4, 0.5))
    cmds.parent(camera, orbit)
    cmds.setKeyframe(orbit, attribute="rotateY", time=1, value=-18.0)
    cmds.setKeyframe(orbit, attribute="rotateY", time=frame_count, value=342.0)
    cmds.keyTangent(orbit, attribute="rotateY", inTangentType="linear", outTangentType="linear")

    skydome_node = cmds.shadingNode("aiSkyDomeLight", asLight=True, name=base + "_SkyShape")
    skydome_transform, skydome_shape = _light_nodes(cmds, skydome_node)
    physical_sky = None
    environment_texture = None
    if environment is not None:
        environment_texture = cmds.shadingNode("file", asTexture=True, name=base + "_EnvironmentHDR")
        _set_attr(cmds, environment_texture, "fileTextureName", str(environment["path"]).replace("\\", "/"))
        _set_attr(cmds, environment_texture, "ignoreColorSpaceFileRules", True)
        _set_attr(cmds, environment_texture, "colorSpace", "Raw")
        cmds.connectAttr(environment_texture + ".outColor", skydome_shape + ".color", force=True)
        cmds.xform(skydome_transform, rotation=(0.0, float(environment_rotation), 0.0))
        _set_attr(cmds, skydome_shape, "exposure", float(environment_exposure))
        _set_attr(cmds, skydome_shape, "aiExposure", float(environment_exposure))
    else:
        physical_sky = cmds.shadingNode("aiPhysicalSky", asUtility=True, name=base + "_PhysicalSky")
        _set_attr(cmds, physical_sky, "turbidity", 2.6)
        _set_attr(cmds, physical_sky, "groundAlbedo", (0.18, 0.2, 0.16))
        _set_attr(cmds, physical_sky, "useDegrees", True)
        _set_attr(cmds, physical_sky, "elevation", 42.0)
        _set_attr(cmds, physical_sky, "azimuth", 112.0)
        _set_attr(cmds, physical_sky, "sunSize", 2.2)
        _set_attr(cmds, physical_sky, "intensity", 1.65)
        cmds.connectAttr(physical_sky + ".outColor", skydome_shape + ".color", force=True)
    _set_attr(cmds, skydome_shape, "intensity", 1.0)

    key_node = cmds.shadingNode("aiAreaLight", asLight=True, name=base + "_KeyShape")
    key_transform, key_shape = _light_nodes(cmds, key_node)
    cmds.xform(key_transform, worldSpace=True, translation=(10.0, 13.0, 16.0), scale=(5.0, 5.0, 5.0))
    _look_at(cmds, key_transform, (0.0, 3.2, 1.0))
    _set_attr(cmds, key_shape, "color", (1.0, 0.88, 0.72))
    _set_attr(cmds, key_shape, "intensity", 1.0)
    _set_attr(cmds, key_shape, "exposure", 3.25 if environment is not None else 2.5)
    _set_attr(cmds, key_shape, "aiExposure", 3.25 if environment is not None else 2.5)
    _set_attr(cmds, key_shape, "samples", 3)
    _set_attr(cmds, key_shape, "aiSamples", 3)

    cmds.parent(orbit, skydome_transform, key_transform, root)
    _set_attr(cmds, "defaultRenderGlobals", "currentRenderer", "arnold")
    _set_attr(cmds, "defaultResolution", "width", 1280)
    _set_attr(cmds, "defaultResolution", "height", 720)
    _set_attr(cmds, "defaultResolution", "deviceAspectRatio", 16.0 / 9.0)
    _set_attr(cmds, "defaultRenderGlobals", "startFrame", 1.0)
    _set_attr(cmds, "defaultRenderGlobals", "endFrame", float(frame_count))
    realistic = look == "realistic"
    _set_attr(cmds, "defaultArnoldRenderOptions", "AASamples", 6 if realistic else 4)
    _set_attr(cmds, "defaultArnoldRenderOptions", "GIDiffuseSamples", 3 if realistic else 2)
    _set_attr(cmds, "defaultArnoldRenderOptions", "GISpecularSamples", 3 if realistic else 2)
    _set_attr(cmds, "defaultArnoldRenderOptions", "GITransmissionSamples", 3 if realistic else 2)
    _set_attr(cmds, "defaultArnoldRenderOptions", "enableAdaptiveSampling", realistic)
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
        "lighting": {
            "skydome": skydome_shape,
            "physical_sky": physical_sky,
            "environment_texture": environment_texture,
            "environment_asset_id": environment.get("asset_id") if environment is not None else None,
            "key_light": key_shape,
        },
    }


def _cleanup_generated_nodes(cmds: Any, base: str, root_name: str) -> None:
    candidates: List[str] = []
    if cmds.objExists(root_name):
        candidates.append(root_name)
    for pattern in (
        base + "_M_*",
        base + "_M_*SG",
        base + "_PhysicalSky",
        base + "_EnvironmentHDR",
    ):
        candidates.extend(cmds.ls(pattern) or [])
    existing = [node for node in dict.fromkeys(candidates) if cmds.objExists(node)]
    if existing:
        cmds.delete(existing)


def generate_house(
    cmds: Any,
    material_assets: Mapping[str, Mapping[str, Any]],
    workspace_dir: str,
    seed: Optional[int] = None,
    style: str = "craftsman",
    look: str = "realistic",
    name: str = "RealisticHouse",
    replace: bool = True,
    frame_count: int = 96,
    environment_asset: Optional[Mapping[str, Any]] = None,
    environment_rotation: float = 0.0,
    environment_exposure: float = 0.0,
    progress: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """Create geometry, Arnold look-dev, lighting, and camera in the current scene."""
    _emit_progress(progress, 0, "Validating generation request")
    if not 24 <= int(frame_count) <= 240:
        raise ValueError("frame_count must be between 24 and 240")
    normalized_look = str(look).strip().lower()
    if normalized_look not in SUPPORTED_LOOKS:
        raise ValueError("look must be one of: {}".format(", ".join(SUPPORTED_LOOKS)))
    design = design_house(seed=seed, style=style)
    _emit_progress(progress, 5, "Preparing CC0 material and HDR assets")
    texture_context = prepare_textures(material_assets, workspace_dir, environment_asset)
    _emit_progress(progress, 12, "Loading Maya, Bifrost, and Arnold plugins")
    if not cmds.pluginInfo("mayaVnnPlugin", query=True, loaded=True):
        cmds.loadPlugin("mayaVnnPlugin", quiet=True)
    if not cmds.pluginInfo("bifrostGraph", query=True, loaded=True):
        cmds.loadPlugin("bifrostGraph", quiet=True)
    if not cmds.pluginInfo("mtoa", query=True, loaded=True):
        cmds.loadPlugin("mtoa", quiet=True)
    base = _safe_name(name)
    root_name = base + "_ROOT"
    if cmds.objExists(root_name) and not replace:
        raise ValueError(f"{root_name} already exists; pass replace=true")
    build_started = False
    try:
        with _maya_generation_guard(cmds):
            _emit_progress(progress, 18, "Cleaning the previous generated house")
            _cleanup_generated_nodes(cmds, base, root_name)
            root = cmds.group(empty=True, name=root_name)
            build_started = True
            _emit_progress(progress, 24, "Creating Arnold PBR materials")
            materials = _create_materials(cmds, base, texture_context["materials"], design, normalized_look)
            _emit_progress(progress, 35, "Building Bifrost structure")
            graphs = _build_graphs(cmds, base, root, design, materials, progress=progress)
            _emit_progress(progress, 65, "Instancing architectural details")
            details = _build_details(cmds, base, root, design, materials, progress=progress)
            _emit_progress(progress, 90, "Computing bounds and staging the Arnold scene")
            bounds = [float(value) for value in cmds.exactWorldBoundingBox(root)]
            staging = _stage_scene(
                cmds,
                base,
                root,
                int(frame_count),
                normalized_look,
                texture_context["environment"],
                environment_rotation,
                environment_exposure,
            )
            _emit_progress(progress, 97, "Finalizing the generated scene")
    except Exception:
        if build_started:
            with suppress(Exception):
                _cleanup_generated_nodes(cmds, base, root_name)
        raise
    cmds.select(root, replace=True)
    cmds.refresh(force=True)
    _emit_progress(progress, 100, "House generation complete")
    return {
        "name": base,
        "root": root,
        "style": design.style,
        "look": normalized_look,
        "seed": design.seed,
        "features": list(design.features),
        "part_count": len(design.parts),
        "graphs": graphs,
        "details": details,
        "materials": materials,
        "bounds": bounds,
        "texture_manifest": texture_context["manifest"],
        "texture_assets": texture_context["materials"],
        "environment_asset": texture_context["environment"],
        **staging,
    }


_DIALOGS: List[Any] = []


def show_generator_dialog(
    material_assets: Mapping[str, Mapping[str, Any]],
    workspace_dir: str,
    name: str = "RealisticHouse",
    seed: Optional[int] = None,
    style: str = "craftsman",
    look: str = "realistic",
    environment_asset: Optional[Mapping[str, Any]] = None,
    environment_rotation: float = 0.0,
    environment_exposure: float = 0.0,
) -> Dict[str, Any]:
    """Open a compact PySide generator that reuses the standalone contract."""
    import maya.cmds as cmds  # noqa: PLC0415

    if cmds.about(batch=True):
        raise RuntimeError("show_house_generator requires interactive Maya; use generate_realistic_house in standalone")
    normalized_style = str(style).strip().lower()
    if normalized_style not in SUPPORTED_STYLES:
        raise ValueError("style must be one of: {}".format(", ".join(SUPPORTED_STYLES)))
    normalized_look = str(look).strip().lower()
    if normalized_look not in SUPPORTED_LOOKS:
        raise ValueError("look must be one of: {}".format(", ".join(SUPPORTED_LOOKS)))
    try:
        from PySide6 import QtCore, QtWidgets  # type: ignore[import-not-found]  # noqa: PLC0415
    except ImportError:
        from PySide2 import QtCore, QtWidgets  # type: ignore[import-not-found,no-redef]  # noqa: PLC0415

    class HouseGeneratorDialog(QtWidgets.QDialog):
        def __init__(self) -> None:
            super().__init__(QtWidgets.QApplication.activeWindow())
            self._busy = False
            self._progress_dialog = None
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
            self.look_combo = QtWidgets.QComboBox()
            self.look_combo.addItems(list(SUPPORTED_LOOKS))
            self.look_combo.setCurrentText(normalized_look)
            form.addRow("House name", self.name_edit)
            form.addRow("Seed", self.seed_spin)
            form.addRow("Style", self.style_combo)
            form.addRow("Material look", self.look_combo)
            layout.addLayout(form)
            assets_label = QtWidgets.QLabel(
                "PBR: "
                + ", ".join("{}={}".format(role, material_assets[role].get("asset_id")) for role in TEXTURE_ROLES)
                + (
                    "\nHDR: {}".format(environment_asset.get("asset_id"))
                    if environment_asset is not None
                    else "\nHDR: Arnold physical sky"
                )
            )
            assets_label.setWordWrap(True)
            layout.addWidget(assets_label)
            self.status = QtWidgets.QLabel("Ready")
            layout.addWidget(self.status)
            buttons = QtWidgets.QHBoxLayout()
            self.generate_button = QtWidgets.QPushButton("Generate")
            self.random_button = QtWidgets.QPushButton("Randomize")
            self.close_button = QtWidgets.QPushButton("Close")
            buttons.addWidget(self.generate_button)
            buttons.addWidget(self.random_button)
            buttons.addStretch(1)
            buttons.addWidget(self.close_button)
            layout.addLayout(buttons)
            self.generate_button.clicked.connect(self.generate)
            self.random_button.clicked.connect(self.randomize)
            self.close_button.clicked.connect(self.close)

        def _set_busy(self, busy: bool) -> None:
            self._busy = busy
            self.generate_button.setEnabled(not busy)
            self.random_button.setEnabled(not busy)
            self.close_button.setEnabled(not busy)
            self.name_edit.setEnabled(not busy)
            self.seed_spin.setEnabled(not busy)
            self.style_combo.setEnabled(not busy)
            self.look_combo.setEnabled(not busy)

        def closeEvent(self, event: Any) -> None:  # noqa: N802
            if self._busy:
                event.ignore()
                self.status.setText("Generation is active; use Cancel on the progress dialog")
                return
            super().closeEvent(event)

        @QtCore.Slot()
        def randomize(self) -> None:
            if self._busy:
                return
            system_random = random.SystemRandom()
            self.seed_spin.setValue(system_random.randint(0, MAX_SEED))
            self.style_combo.setCurrentIndex(system_random.randrange(len(SUPPORTED_STYLES)))
            self.look_combo.setCurrentIndex(system_random.randrange(len(SUPPORTED_LOOKS)))
            self.generate()

        @QtCore.Slot()
        def generate(self) -> None:
            if self._busy:
                return
            self._set_busy(True)
            self.status.setText("Queued on Maya's main-thread QTimer...")
            progress_dialog = QtWidgets.QProgressDialog("Preparing generation...", "Cancel", 0, 100, self)
            progress_dialog.setWindowTitle("Generating procedural house")
            progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setAutoClose(False)
            progress_dialog.setAutoReset(False)
            progress_dialog.setValue(0)
            self._progress_dialog = progress_dialog
            progress_dialog.show()
            QtCore.QTimer.singleShot(0, self._run_generation)

        @QtCore.Slot()
        def _run_generation(self) -> None:
            progress_dialog = self._progress_dialog
            if progress_dialog is None:
                self._set_busy(False)
                return

            def report_progress(value: int, message: str) -> None:
                if progress_dialog.wasCanceled():
                    raise GenerationCancelled("generation cancelled by user")
                progress_dialog.setLabelText(message)
                progress_dialog.setValue(value)
                self.status.setText(f"{value}% · {message}")
                QtWidgets.QApplication.processEvents()
                if progress_dialog.wasCanceled():
                    raise GenerationCancelled("generation cancelled by user")

            try:
                result = generate_house(
                    cmds,
                    material_assets=material_assets,
                    workspace_dir=workspace_dir,
                    seed=self.seed_spin.value(),
                    style=self.style_combo.currentText(),
                    look=self.look_combo.currentText(),
                    name=self.name_edit.text(),
                    replace=True,
                    environment_asset=environment_asset,
                    environment_rotation=environment_rotation,
                    environment_exposure=environment_exposure,
                    progress=report_progress,
                )
                for panel in cmds.getPanel(type="modelPanel") or []:
                    cmds.modelPanel(panel, edit=True, camera=result["camera"])
                cmds.refresh(force=True)
                self.status.setText(
                    "{} · {} · seed {} · {} detailed parts".format(
                        result["style"],
                        result["look"],
                        result["seed"],
                        result["part_count"],
                    )
                )
            except GenerationCancelled:  # pragma: no cover - Maya UI path
                self.status.setText("Cancelled · partial generation cleaned up")
            except Exception as exc:  # pragma: no cover - Maya UI path
                self.status.setText(f"Failed: {exc}")
            finally:
                progress_dialog.close()
                progress_dialog.deleteLater()
                self._progress_dialog = None
                self._set_busy(False)

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
        "look": dialog.look_combo.currentText(),
        "mode": "interactive_qt",
    }
