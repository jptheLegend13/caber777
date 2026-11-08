"""Procedural geometry generation for CABER.

Converts a :class:`BuildingSpec` into a renderable scene graph of box
primitives, wall openings, slabs, roof, outdoor areas, objects and lights. The
output is renderer-agnostic: a flat list of transformed primitives that the
Three.js viewport (or an offline renderer) can consume directly.

Openings are handled by splitting a wall into segments around each door and
window, which keeps the geometry watertight without CSG operations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from level5.caber.models import (
    BuildingSpec,
    Dimensions,
    Material,
    Opening,
    PlacedObject,
    Room,
    Vec3,
)

WALL_THICKNESS = 0.2
SLAB_THICKNESS = 0.15


@dataclass
class Primitive:
    """One renderable box."""

    id: str
    kind: str
    name: str
    position: list[float]
    size: list[float]
    rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    color: str = "#cccccc"
    roughness: float = 0.7
    metalness: float = 0.0
    opacity: float = 1.0
    room_id: str | None = None
    object_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "position": self.position,
            "size": self.size,
            "rotation": self.rotation,
            "material": {
                "color": self.color,
                "roughness": self.roughness,
                "metalness": self.metalness,
                "opacity": self.opacity,
            },
            "room_id": self.room_id,
            "object_id": self.object_id,
        }


_MATERIALS: dict[str, Material] = {
    "concrete": Material(name="concrete", color="#d6d3cd", roughness=0.85),
    "plaster": Material(name="plaster", color="#f2efe9", roughness=0.9),
    "brick": Material(name="brick", color="#a9645a", roughness=0.9),
    "wood": Material(name="wood", color="#9c6b3f", roughness=0.6),
    "glass": Material(name="glass", color="#bcd9e8", roughness=0.05, metalness=0.0, opacity=0.35),
    "tile": Material(name="tile", color="#dfe3e6", roughness=0.3),
    "metal": Material(name="metal", color="#8a8f96", roughness=0.3, metalness=0.9),
    "marble": Material(name="marble", color="#eceae6", roughness=0.25),
    "grass": Material(name="grass", color="#5d8a4a", roughness=1.0),
    "water": Material(name="water", color="#2f6f8f", roughness=0.1, opacity=0.75),
    "stone": Material(name="stone", color="#b8b2a7", roughness=0.95),
    "fabric": Material(name="fabric", color="#7d8ca3", roughness=1.0),
    "dark_wood": Material(name="dark_wood", color="#5b3f2a", roughness=0.6),
    "white": Material(name="white", color="#fbfbfb", roughness=0.8),
}


def material_for(name: str) -> Material:
    return _MATERIALS.get(name, _MATERIALS["concrete"])


def build_scene(spec: BuildingSpec) -> dict[str, Any]:
    """Generate the complete scene graph for a building specification."""
    primitives: list[Primitive] = []
    block = spec.block1

    # Ground plane and outdoor areas ------------------------------------- #
    footprint = block.footprint
    pad = 6.0
    primitives.append(
        Primitive(
            id="ground",
            kind="ground",
            name="Ground",
            position=[footprint.width / 2, -0.1, footprint.depth / 2],
            size=[footprint.width + pad * 2, 0.2, footprint.depth + pad * 2],
            color="#6f7a63",
            roughness=1.0,
        )
    )
    for area in block.outdoor_areas:
        mat = material_for(area.material)
        primitives.append(
            Primitive(
                id=area.id,
                kind="outdoor",
                name=area.name,
                position=[
                    area.position.x + area.dimensions.width / 2,
                    area.position.y + 0.02,
                    area.position.z + area.dimensions.depth / 2,
                ],
                size=[area.dimensions.width, 0.05, area.dimensions.depth],
                color=mat.color,
                roughness=mat.roughness,
                opacity=mat.opacity,
            )
        )

    # Floors, ceilings and walls ----------------------------------------- #
    for room in block.rooms:
        primitives.append(_floor(room))
        primitives.append(_ceiling(room, block.floors))
        primitives.extend(_walls_with_openings(room, block.openings, block.interior_material))
    primitives.extend(_stair_geometry(block))

    # Roof ---------------------------------------------------------------- #
    primitives.extend(_roof(spec))

    # Objects ------------------------------------------------------------- #
    for obj in spec.all_objects:
        primitives.append(_object_primitive(obj))

    # Lights -------------------------------------------------------------- #
    lights = _normalise_lights(spec.lighting) or _normalise_lights(
        [
            {"kind": "ambient", "intensity": 0.35, "color": "#ffffff"},
            {"kind": "directional", "intensity": 1.4, "position": {"x": 30, "y": 40, "z": 20}, "color": "#fff5e6"},
        ]
    )

    bounds = _bounds(primitives)
    return {
        "title": spec.title,
        "units": "metres",
        "primitives": [p.as_dict() for p in primitives],
        "lights": lights,
        "bounds": bounds,
        "stats": {
            "rooms": len(block.rooms),
            "objects": len(spec.all_objects),
            "primitives": len(primitives),
            "floor_area": round(block.total_floor_area, 2),
            "floors": block.floors,
        },
        "metadata": {
            "category": block.category.value,
            "style": block.style.value,
            "roof_type": block.roof_type,
            "environment": spec.environment,
        },
    }


def _floor(room: Room) -> Primitive:
    return Primitive(
        id=f"{room.id}_floor",
        kind="floor",
        name=f"{room.name} floor",
        position=[
            room.position.x + room.dimensions.width / 2,
            room.position.y - SLAB_THICKNESS / 2,
            room.position.z + room.dimensions.depth / 2,
        ],
        size=[room.dimensions.width, SLAB_THICKNESS, room.dimensions.depth],
        color="#cfc9bd",
        roughness=0.85,
        room_id=room.id,
    )


def _ceiling(room: Room, total_floors: int) -> Primitive:
    return Primitive(
        id=f"{room.id}_ceiling",
        kind="ceiling",
        name=f"{room.name} ceiling",
        position=[
            room.position.x + room.dimensions.width / 2,
            room.position.y + room.dimensions.height + SLAB_THICKNESS / 2,
            room.position.z + room.dimensions.depth / 2,
        ],
        size=[room.dimensions.width, SLAB_THICKNESS, room.dimensions.depth],
        color="#e8e4dc",
        roughness=0.9,
        room_id=room.id,
    )


def _walls_with_openings(
    room: Room, openings: list[Opening], material_name: str
) -> list[Primitive]:
    mat = material_for(material_name)
    walls: list[Primitive] = []
    width, depth, height = (
        room.dimensions.width,
        room.dimensions.height,
        room.dimensions.depth,
    )
    height = room.dimensions.height

    wall_defs = {
        "north": (room.position.z + depth, "x", width, room.position.x),
        "south": (room.position.z, "x", width, room.position.x),
        "east": (room.position.x + width, "z", depth, room.position.z),
        "west": (room.position.x, "z", depth, room.position.z),
    }
    room_openings = [o for o in openings if o.room_id == room.id]

    for wall, (fixed, axis, length, start) in wall_defs.items():
        on_wall = sorted(
            [o for o in room_openings if o.wall == wall], key=lambda o: o.offset
        )
        for index, seg in enumerate(_wall_segments(length, height, on_wall)):
            seg_start, seg_len, y0, y1 = seg
            if seg_len <= 1e-3 or (y1 - y0) <= 1e-3:
                continue
            if axis == "x":
                pos = [
                    start + seg_start + seg_len / 2,
                    room.position.y + (y0 + y1) / 2,
                    fixed,
                ]
                size = [seg_len, y1 - y0, WALL_THICKNESS]
            else:
                pos = [
                    fixed,
                    room.position.y + (y0 + y1) / 2,
                    start + seg_start + seg_len / 2,
                ]
                size = [WALL_THICKNESS, y1 - y0, seg_len]
            walls.append(
                Primitive(
                    id=f"{room.id}_{wall}_{index}",
                    kind="wall",
                    name=f"{room.name} {wall} wall",
                    position=pos,
                    size=size,
                    color=mat.color,
                    roughness=mat.roughness,
                    room_id=room.id,
                )
            )

    # Door and window frames (visual only, keeps openings legible).
    for opening in room_openings:
        walls.append(_opening_frame(room, opening))
    return walls


def _wall_segments(
    length: float, height: float, openings: list[Opening]
) -> list[tuple[float, float, float, float]]:
    """Split a wall into (start, len, y0, y1) solid segments."""
    segments: list[tuple[float, float, float, float]] = []
    cursor = 0.0
    for opening in openings:
        start = max(0.0, min(opening.offset, length))
        end = min(length, start + opening.width)
        if start > cursor:
            segments.append((cursor, start - cursor, 0.0, height))
        sill = max(0.0, opening.sill)
        top = min(height, sill + opening.height)
        if opening.kind == "window" and sill > 0:
            segments.append((start, end - start, 0.0, sill))
        if top < height:
            segments.append((start, end - start, top, height))
        cursor = max(cursor, end)
    if cursor < length:
        segments.append((cursor, length - cursor, 0.0, height))
    return segments


def _opening_frame(room: Room, opening: Opening) -> Primitive:
    """A thin translucent panel marking a door or window opening."""
    width, depth = room.dimensions.width, room.dimensions.depth
    thickness = 0.06
    if opening.wall == "north":
        pos = [room.position.x + opening.offset + opening.width / 2,
               room.position.y + opening.sill + opening.height / 2,
               room.position.z + depth]
        size = [opening.width, opening.height, thickness]
    elif opening.wall == "south":
        pos = [room.position.x + opening.offset + opening.width / 2,
               room.position.y + opening.sill + opening.height / 2,
               room.position.z]
        size = [opening.width, opening.height, thickness]
    elif opening.wall == "east":
        pos = [room.position.x + width,
               room.position.y + opening.sill + opening.height / 2,
               room.position.z + opening.offset + opening.width / 2]
        size = [thickness, opening.height, opening.width]
    else:
        pos = [room.position.x,
               room.position.y + opening.sill + opening.height / 2,
               room.position.z + opening.offset + opening.width / 2]
        size = [thickness, opening.height, opening.width]

    if opening.kind == "window":
        mat = material_for("glass")
    else:
        mat = material_for("wood")
    return Primitive(
        id=opening.id,
        kind=opening.kind,
        name=f"{room.name} {opening.kind}",
        position=pos,
        size=size,
        color=mat.color,
        roughness=mat.roughness,
        metalness=mat.metalness,
        opacity=mat.opacity,
        room_id=room.id,
    )


def _stair_geometry(block: BuildingBlock) -> list[Primitive]:
    """Render each stair connection as a flight of steps."""
    primitives: list[Primitive] = []
    for opening in block.openings:
        if opening.kind != "stair" or opening.connects_to is None:
            continue
        upper = next((r for r in block.rooms if r.id == opening.room_id), None)
        lower = next((r for r in block.rooms if r.id == opening.connects_to), None)
        if upper is None or lower is None:
            continue
        rise = max(0.5, upper.position.y - lower.position.y)
        run = max(1.2, min(4.0, rise * 1.3))
        steps = max(6, int(rise / 0.19))
        step_rise = rise / steps
        step_run = run / steps
        base_x = upper.position.x + 0.5
        base_z = upper.position.z + 0.5
        for index in range(steps):
            y = lower.position.y + (index + 1) * step_rise
            primitives.append(
                Primitive(
                    id=f"{opening.id}_step{index}",
                    kind="stair",
                    name="Stair step",
                    position=[base_x, y - step_rise / 2, base_z + index * step_run],
                    size=[opening.width, step_rise, step_run],
                    color="#9c6b3f",
                    roughness=0.6,
                    room_id=upper.id,
                )
            )
    return primitives


def _roof(spec: BuildingSpec) -> list[Primitive]:
    block = spec.block1
    footprint = block.footprint
    top = footprint.height
    roof_type = block.roof_type
    mat = material_for(block.exterior_material)
    primitives: list[Primitive] = []
    if roof_type in ("gable", "hip"):
        rise = max(1.2, min(3.5, footprint.width * 0.25))
        # Two sloped slabs forming a ridge along the depth axis.
        angle = math.degrees(math.atan2(rise, footprint.width / 2))
        slope_len = math.hypot(footprint.width / 2, rise)
        for sign in (-1, 1):
            primitives.append(
                Primitive(
                    id=f"roof_{'east' if sign > 0 else 'west'}",
                    kind="roof",
                    name="Roof",
                    position=[
                        footprint.width / 2 + sign * footprint.width / 4,
                        top + rise / 2,
                        footprint.depth / 2,
                    ],
                    size=[slope_len, 0.18, footprint.depth + 0.6],
                    rotation=[0.0, 0.0, -sign * angle],
                    color=mat.color,
                    roughness=mat.roughness,
                )
            )
    elif roof_type == "dome":
        primitives.append(
            Primitive(
                id="roof_dome",
                kind="roof",
                name="Dome",
                position=[footprint.width / 2, top + 0.1, footprint.depth / 2],
                size=[footprint.width, max(1.0, footprint.width * 0.4), footprint.depth],
                color=mat.color,
                roughness=mat.roughness,
            )
        )
    else:
        primitives.append(
            Primitive(
                id="roof_slab",
                kind="roof",
                name="Roof",
                position=[footprint.width / 2, top + 0.1, footprint.depth / 2],
                size=[footprint.width + 0.6, 0.22, footprint.depth + 0.6],
                color=mat.color,
                roughness=mat.roughness,
            )
        )
    return primitives


def _object_primitive(obj: PlacedObject) -> Primitive:
    return Primitive(
        id=obj.id,
        kind=obj.category,
        name=obj.name,
        position=[
            obj.position.x + obj.dimensions.width * obj.scale.x / 2,
            obj.position.y + obj.dimensions.height * obj.scale.y / 2,
            obj.position.z + obj.dimensions.depth * obj.scale.z / 2,
        ],
        size=[
            obj.dimensions.width * obj.scale.x,
            obj.dimensions.height * obj.scale.y,
            obj.dimensions.depth * obj.scale.z,
        ],
        rotation=[obj.rotation.x, obj.rotation.y, obj.rotation.z],
        color=obj.material.color,
        roughness=obj.material.roughness,
        metalness=obj.material.metalness,
        opacity=obj.material.opacity,
        room_id=obj.room_id,
        object_id=obj.id,
    )


def _normalise_lights(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lights: list[dict[str, Any]] = []
    for index, light in enumerate(raw):
        kind = light.get("kind", "point")
        if kind not in ("ambient", "directional", "point", "spot"):
            kind = "point"
        position = light.get("position") or {}
        lights.append(
            {
                "id": f"light_{index}",
                "kind": kind,
                "intensity": float(light.get("intensity", 1.0)),
                "color": light.get("color", "#ffffff"),
                "position": [
                    float(position.get("x", 0.0)),
                    float(position.get("y", 10.0)),
                    float(position.get("z", 0.0)),
                ],
            }
        )
    return lights


def _bounds(primitives: list[Primitive]) -> dict[str, list[float]]:
    if not primitives:
        return {"min": [0, 0, 0], "max": [10, 10, 10], "center": [5, 5, 5], "size": [10, 10, 10]}
    mins = [math.inf, math.inf, math.inf]
    maxs = [-math.inf, -math.inf, -math.inf]
    for prim in primitives:
        if prim.kind == "ground":
            continue
        for axis in range(3):
            half = prim.size[axis] / 2
            mins[axis] = min(mins[axis], prim.position[axis] - half)
            maxs[axis] = max(maxs[axis], prim.position[axis] + half)
    if not all(math.isfinite(v) for v in mins + maxs):
        mins, maxs = [0, 0, 0], [10, 10, 10]
    center = [(mins[i] + maxs[i]) / 2 for i in range(3)]
    size = [maxs[i] - mins[i] for i in range(3)]
    return {"min": mins, "max": maxs, "center": center, "size": size}
