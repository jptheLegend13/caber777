"""Architectural understanding: request -> BuildingSpec (three blocks).

The model proposes a coherent building; the geometry engine then builds it and
the validator rejects impossible layouts. Defaults are chosen so an incomplete
model response still yields a valid, buildable structure.
"""

from __future__ import annotations

import logging
from typing import Any

from level5.caber.models import (
    ArchitecturalStyle,
    BuildingBlock,
    BuildingCategory,
    BuildingSpec,
    Dimensions,
    Material,
    Opening,
    OutdoorArea,
    PlacedObject,
    Room,
    Vec3,
)
from level5.llm.client import LLMClient, get_llm_client

logger = logging.getLogger("level5.caber.architect")

_CATEGORIES = [c.value for c in BuildingCategory]
_STYLES = [s.value for s in ArchitecturalStyle]

_SYSTEM = """You are the architectural design intelligence of CABER inside LEVEL 5.

Convert the user's building request into a complete architectural specification.

Design rules:
- Rooms must tile a rectangular footprint without overlapping, on a grid.
- Room `position` is the minimum corner in metres: x (east), y (floor height), z (north).
- Floor 0 sits at y=0. Each room's `floor` is its storey index.
- Adjacent rooms must share a wall within 0.05 m so doors connect them.
- Give every room a name, purpose, dimensions and material.
- Place furniture and objects inside the room that owns them, with coordinates
  inside that room's bounds.
- Include lighting and a short design narrative.

Respond with ONE JSON object:
{
  "title": string,
  "narrative": string,
  "block1": {
    "category": one of %(categories)s,
    "style": one of %(styles)s,
    "site_shape": "rectangle"|"l_shape"|"u_shape"|"circular"|"irregular",
    "floors": int,
    "exterior_material": string,
    "interior_material": string,
    "roof_type": "flat"|"gable"|"hip"|"shed"|"dome",
    "rooms": [{"name": string, "purpose": string, "floor": int,
               "position": {"x": number, "y": number, "z": number},
               "dimensions": {"width": number, "height": number, "depth": number},
               "material": string}],
    "outdoor_areas": [{"name": string, "kind": string,
                       "position": {"x": number, "y": number, "z": number},
                       "dimensions": {"width": number, "height": number, "depth": number}}]
  },
  "objects": [{"name": string, "category": "furniture"|"appliance"|"decor"|"fixture"|"component"|"character"|"light",
               "room": string,  // room NAME this object belongs to
               "position": {"x": number, "y": number, "z": number},
               "rotation": {"x": number, "y": number, "z": number},
               "dimensions": {"width": number, "height": number, "depth": number},
               "material": {"name": string, "color": "#rrggbb", "roughness": number, "metalness": number},
               "appearance": string,
               "behaviors": [string], "interactions": [string], "states": [string]}],
  "lighting": [{"kind": "ambient"|"directional"|"point"|"spot", "intensity": number,
                "position": {"x": number, "y": number, "z": number}, "color": "#rrggbb"}],
  "environment": {"sky": string, "terrain": string, "time_of_day": string}
}""" % {"categories": _CATEGORIES, "styles": _STYLES}


class ArchitecturalArchitect:
    """Turns a natural-language building request into a :class:`BuildingSpec`."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm_client()

    async def design(self, request: str, *, preferences: str = "") -> BuildingSpec:
        user = request.strip()
        if preferences:
            user += f"\n\nPERSONAL PREFERENCES: {preferences.strip()}"
        data, usage = await self.llm.chat_json(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            temperature=0.4,
            max_tokens=6000,
        )
        logger.info("architecture designed (%s tokens)", usage.total_tokens)
        return self._to_spec(request, data)

    def _to_spec(self, request: str, data: dict[str, Any]) -> BuildingSpec:
        raw_b1 = data.get("block1") or {}
        rooms = self._rooms(raw_b1.get("rooms") or [])
        if not rooms:
            rooms = _default_rooms()

        block1 = BuildingBlock(
            category=_coerce(raw_b1.get("category"), _CATEGORIES, BuildingCategory.HOUSE),
            style=_coerce(raw_b1.get("style"), _STYLES, ArchitecturalStyle.MODERN),
            site_shape=raw_b1.get("site_shape", "rectangle")
            if raw_b1.get("site_shape") in ("rectangle", "l_shape", "u_shape", "circular", "irregular")
            else "rectangle",
            floors=max(1, int(raw_b1.get("floors", _count_floors(rooms)))),
            exterior_material=str(raw_b1.get("exterior_material", "concrete")),
            interior_material=str(raw_b1.get("interior_material", "plaster")),
            roof_type=raw_b1.get("roof_type", "flat")
            if raw_b1.get("roof_type") in ("flat", "gable", "hip", "shed", "dome")
            else "flat",
            rooms=rooms,
            outdoor_areas=self._outdoor(raw_b1.get("outdoor_areas") or []),
            notes=str(raw_b1.get("notes", "")),
        )
        block1.openings = _auto_openings(block1)

        room_by_name = {r.name.lower(): r for r in rooms}
        objects = self._objects(data.get("objects") or [], room_by_name)

        lighting = data.get("lighting")
        if not isinstance(lighting, list) or not lighting:
            lighting = _default_lighting()

        return BuildingSpec(
            request=request,
            title=str(data.get("title") or "Designed building"),
            block1=block1,
            block2=[o for o in objects if o.category != "character"],
            block3=[o for o in objects if o.category == "character"],
            lighting=[l for l in lighting if isinstance(l, dict)],
            environment=data.get("environment") if isinstance(data.get("environment"), dict) else {},
            narrative=str(data.get("narrative", "")),
        )

    def _rooms(self, raw: list[Any]) -> list[Room]:
        rooms: list[Room] = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            rooms.append(
                Room(
                    name=str(item["name"])[:60],
                    purpose=str(item.get("purpose", "living")),
                    floor=int(item.get("floor", 0)),
                    position=_vec(item.get("position")),
                    dimensions=_dims(item.get("dimensions")),
                    material=str(item.get("material", "plaster")),
                )
            )
        return rooms[:24]

    def _outdoor(self, raw: list[Any]) -> list[OutdoorArea]:
        areas: list[OutdoorArea] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind", "garden")
            areas.append(
                OutdoorArea(
                    name=str(item.get("name", "outdoor"))[:60],
                    kind=kind if kind in ("garden", "terrace", "pool", "courtyard", "deck", "driveway") else "garden",
                    position=_vec(item.get("position")),
                    dimensions=_dims(item.get("dimensions")),
                    material=str(item.get("material", "grass")),
                )
            )
        return areas[:8]

    def _objects(
        self, raw: list[Any], room_by_name: dict[str, Room]
    ) -> list[PlacedObject]:
        objects: list[PlacedObject] = []
        valid_categories = (
            "furniture", "appliance", "decor", "fixture", "component", "character", "light"
        )
        for item in raw:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            room_name = str(item.get("room", "")).lower()
            room = room_by_name.get(room_name)
            category = item.get("category", "furniture")
            material_raw = item.get("material") or {}
            material = Material(
                name=str(material_raw.get("name", "default")),
                color=_hex(material_raw.get("color", "#cccccc")),
                roughness=_clamp01(material_raw.get("roughness", 0.7)),
                metalness=_clamp01(material_raw.get("metalness", 0.0)),
            )
            position = _vec(item.get("position"))
            if room is not None:
                position = _clamp_into_room(position, room)
            objects.append(
                PlacedObject(
                    name=str(item["name"])[:60],
                    category=category if category in valid_categories else "furniture",
                    room_id=room.id if room else None,
                    position=position,
                    rotation=_vec(item.get("rotation")),
                    dimensions=_dims(item.get("dimensions")),
                    material=material,
                    appearance=str(item.get("appearance", "")),
                    behaviors=[str(b) for b in (item.get("behaviors") or [])][:8],
                    interactions=[str(i) for i in (item.get("interactions") or [])][:8],
                    states=[str(s) for s in (item.get("states") or [])][:8],
                )
            )
        return objects[:60]


def _coerce(value: Any, allowed: list[str], default: Any) -> Any:
    text = str(value)
    return text if text in allowed else default.value


def _vec(raw: Any) -> Vec3:
    if isinstance(raw, dict):
        return Vec3(
            x=_num(raw.get("x")), y=_num(raw.get("y")), z=_num(raw.get("z"))
        )
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        return Vec3(x=_num(raw[0]), y=_num(raw[1]), z=_num(raw[2]))
    return Vec3()


def _dims(raw: Any) -> Dimensions:
    if isinstance(raw, dict):
        return Dimensions(
            width=_num(raw.get("width"), 1.0),
            height=_num(raw.get("height"), 1.0),
            depth=_num(raw.get("depth"), 1.0),
        )
    return Dimensions()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp01(value: Any) -> float:
    return min(1.0, max(0.0, _num(value, 0.5)))


def _hex(value: Any) -> str:
    text = str(value or "#cccccc")
    return text if text.startswith("#") and len(text) in (4, 7) else "#cccccc"


def _clamp_into_room(position: Vec3, room: Room) -> Vec3:
    """Keep an object inside the room that owns it."""
    margin = 0.05
    x = min(max(position.x, room.position.x + margin), room.position.x + room.dimensions.width - margin)
    z = min(max(position.z, room.position.z + margin), room.position.z + room.dimensions.depth - margin)
    y = max(position.y, room.position.y)
    return Vec3(x=round(x, 3), y=round(y, 3), z=round(z, 3))


def _count_floors(rooms: list[Room]) -> int:
    return max((r.floor for r in rooms), default=0) + 1


def _default_rooms() -> list[Room]:
    return [
        Room(name="Living Room", purpose="living", floor=0,
             position=Vec3(x=0, y=0, z=0), dimensions=Dimensions(width=6, height=2.8, depth=5),
             material="plaster"),
        Room(name="Kitchen", purpose="kitchen", floor=0,
             position=Vec3(x=6, y=0, z=0), dimensions=Dimensions(width=4, height=2.8, depth=5),
             material="tile"),
        Room(name="Bedroom", purpose="bedroom", floor=1,
             position=Vec3(x=0, y=3.0, z=0), dimensions=Dimensions(width=5, height=2.8, depth=4),
             material="plaster"),
        Room(name="Bathroom", purpose="bathroom", floor=1,
             position=Vec3(x=5, y=3.0, z=0), dimensions=Dimensions(width=3, height=2.8, depth=4),
             material="tile"),
    ]


def _auto_openings(block: BuildingBlock) -> list[Opening]:
    """Create a door between adjacent rooms and windows on exterior walls."""
    openings: list[Opening] = []
    for room in block.rooms:
        for other in block.rooms:
            if other.id == room.id or other.floor != room.floor:
                continue
            adjacency = _shared_wall(room, other)
            if adjacency and not any(
                o.kind == "door"
                and {o.room_id, o.connects_to} == {room.id, other.id}
                for o in openings
            ):
                wall, offset = adjacency
                openings.append(
                    Opening(
                        kind="door",
                        room_id=room.id,
                        connects_to=other.id,
                        wall=wall,
                        offset=offset,
                        width=0.9,
                        height=2.05,
                    )
                )
        # One window per exterior wall of a ground/first-floor room.
        for wall in ("north", "south", "east", "west"):
            if not _has_neighbour_on_wall(block, room, wall):
                span = room.dimensions.width if wall in ("north", "south") else room.dimensions.depth
                if span >= 2.0:
                    openings.append(
                        Opening(
                            kind="window",
                            room_id=room.id,
                            wall=wall,
                            offset=round(span / 2 - 0.6, 3),
                            width=1.2,
                            height=1.4,
                            sill=0.9,
                            material="glass",
                        )
                    )
    # Stairs connect vertically-adjacent rooms between storeys.
    openings.extend(_auto_stairs(block))
    return openings


def _auto_stairs(block: BuildingBlock) -> list[Opening]:
    """Link each upper floor to the room below it, for vertical circulation."""
    stairs: list[Opening] = []
    floors = sorted({r.floor for r in block.rooms})
    for floor in floors:
        if floor == 0:
            continue
        upper = [r for r in block.rooms if r.floor == floor]
        lower = [r for r in block.rooms if r.floor == floor - 1]
        if not upper or not lower:
            continue
        upper_room = upper[0]
        # Prefer the lower room with the greatest plan overlap.
        lower_room = max(lower, key=lambda r: _overlap_area(r, upper_room))
        stairs.append(
            Opening(
                kind="stair",
                room_id=upper_room.id,
                connects_to=lower_room.id,
                wall="south",
                offset=0.4,
                width=1.2,
                height=upper_room.dimensions.height,
                material="wood",
                rises_to_floor=floor,
            )
        )
    return stairs


def _overlap_area(a: Room, b: Room) -> float:
    dx = min(a.position.x + a.dimensions.width, b.position.x + b.dimensions.width) - max(
        a.position.x, b.position.x
    )
    dz = min(a.position.z + a.dimensions.depth, b.position.z + b.dimensions.depth) - max(
        a.position.z, b.position.z
    )
    return max(0.0, dx) * max(0.0, dz)


def _shared_wall(a: Room, b: Room) -> tuple[str, float] | None:
    tol = 0.05
    # b to the east of a
    if abs((a.position.x + a.dimensions.width) - b.position.x) <= tol and _overlap_z(a, b):
        return ("east", round(max(0.0, (min(a.position.z + a.dimensions.depth, b.position.z + b.dimensions.depth) - max(a.position.z, b.position.z)) / 2 - 0.45), 3))
    if abs((b.position.x + b.dimensions.width) - a.position.x) <= tol and _overlap_z(a, b):
        return ("west", round(max(0.0, (min(a.position.z + a.dimensions.depth, b.position.z + b.dimensions.depth) - max(a.position.z, b.position.z)) / 2 - 0.45), 3))
    if abs((a.position.z + a.dimensions.depth) - b.position.z) <= tol and _overlap_x(a, b):
        return ("north", round(max(0.0, (min(a.position.x + a.dimensions.width, b.position.x + b.dimensions.width) - max(a.position.x, b.position.x)) / 2 - 0.45), 3))
    if abs((b.position.z + b.dimensions.depth) - a.position.z) <= tol and _overlap_x(a, b):
        return ("south", round(max(0.0, (min(a.position.x + a.dimensions.width, b.position.x + b.dimensions.width) - max(a.position.x, b.position.x)) / 2 - 0.45), 3))
    return None


def _overlap_z(a: Room, b: Room) -> bool:
    return min(a.position.z + a.dimensions.depth, b.position.z + b.dimensions.depth) - max(a.position.z, b.position.z) >= 1.0


def _overlap_x(a: Room, b: Room) -> bool:
    return min(a.position.x + a.dimensions.width, b.position.x + b.dimensions.width) - max(a.position.x, b.position.x) >= 1.0


def _has_neighbour_on_wall(block: BuildingBlock, room: Room, wall: str) -> bool:
    for other in block.rooms:
        if other.id == room.id or other.floor != room.floor:
            continue
        if wall == "east" and abs((room.position.x + room.dimensions.width) - other.position.x) <= 0.05 and _overlap_z(room, other):
            return True
        if wall == "west" and abs((other.position.x + other.dimensions.width) - room.position.x) <= 0.05 and _overlap_z(room, other):
            return True
        if wall == "north" and abs((room.position.z + room.dimensions.depth) - other.position.z) <= 0.05 and _overlap_x(room, other):
            return True
        if wall == "south" and abs((other.position.z + other.dimensions.depth) - room.position.z) <= 0.05 and _overlap_x(room, other):
            return True
    return False


def _default_lighting() -> list[dict[str, Any]]:
    return [
        {"kind": "ambient", "intensity": 0.35, "color": "#ffffff"},
        {"kind": "directional", "intensity": 1.4, "position": {"x": 30, "y": 40, "z": 20}, "color": "#fff5e6"},
        {"kind": "point", "intensity": 0.6, "position": {"x": 3, "y": 2.6, "z": 3}, "color": "#ffd9a0"},
    ]
