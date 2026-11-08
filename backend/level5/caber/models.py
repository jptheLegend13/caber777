"""CABER Building Creation Intelligence: the three-block specification.

BLOCK 1 - Building, design and spaces: category, dimensions, site, floors,
           style, rooms (name, purpose, dimensions), materials, doors, windows,
           floor plans, outdoor areas.
BLOCK 2 - Objects and components: furniture, appliances, decor, fixtures,
           architectural components, characters - each with dimensions,
           materials, appearance, id, quantity, behaviour.
BLOCK 3 - Position, actions and behaviours: coordinates, relationships,
           orientation, rotation, scale, interactions, actions, states, events,
           triggers, behaviour rules.

The three blocks together are the contract that drives procedural geometry.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class BuildingCategory(str, Enum):
    HOUSE = "house"
    APARTMENT = "apartment"
    MANSION = "mansion"
    VILLA = "villa"
    GOVERNMENT = "government"
    PRESIDENTIAL = "presidential_residence"
    HOTEL = "hotel"
    OFFICE = "office"
    COMMERCIAL = "commercial"
    PROTECTED_RESIDENCE = "protected_residence"
    FLOATING = "floating_structure"
    OCEAN = "ocean_house"
    MOUNTAIN = "mountain_house"
    FOREST = "forest_building"
    SHELTER = "temporary_shelter"
    FANTASY = "fantasy_house"
    MUSHROOM = "mushroom_house"
    ORIGINAL = "original"


class ArchitecturalStyle(str, Enum):
    MODERN = "modern"
    MINIMALIST = "minimalist"
    CONTEMPORARY = "contemporary"
    TRADITIONAL = "traditional"
    CLASSICAL = "classical"
    INDUSTRIAL = "industrial"
    SCANDINAVIAN = "scandinavian"
    MEDITERRANEAN = "mediterranean"
    JAPANESE = "japanese"
    BRUTALIST = "brutalist"
    FUTURISTIC = "futuristic"
    ORGANIC = "organic"
    FANTASY = "fantasy"


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def as_list(self) -> list[float]:
        return [self.x, self.y, self.z]


class Dimensions(BaseModel):
    """Axis-aligned size in metres (width, height, depth)."""

    width: float = 1.0
    height: float = 1.0
    depth: float = 1.0

    @field_validator("width", "height", "depth")
    @classmethod
    def _positive(cls, value: float) -> float:
        return max(0.05, float(value))

    @property
    def volume(self) -> float:
        return self.width * self.height * self.depth

    @property
    def floor_area(self) -> float:
        return self.width * self.depth


class Material(BaseModel):
    name: str = "default"
    color: str = "#cccccc"
    roughness: float = 0.7
    metalness: float = 0.0
    opacity: float = 1.0
    texture: str | None = None
    emission: str | None = None


class Room(BaseModel):
    """A space in the building (BLOCK 1)."""

    id: str = Field(default_factory=lambda: _id("room"))
    name: str
    purpose: str = "living"
    floor: int = 0
    position: Vec3 = Field(default_factory=Vec3)
    dimensions: Dimensions = Field(default_factory=Dimensions)
    material: str = "plaster"
    doors: list[str] = Field(default_factory=list)  # DoorComponent ids
    windows: list[str] = Field(default_factory=list)  # WindowComponent ids
    connected_rooms: list[str] = Field(default_factory=list)


class Opening(BaseModel):
    """A door or window on a wall of a room."""

    id: str = Field(default_factory=lambda: _id("open"))
    kind: Literal["door", "window", "stair"] = "door"
    room_id: str
    wall: Literal["north", "south", "east", "west"] = "north"
    offset: float = 0.0  # along the wall from its start
    width: float = 0.9
    height: float = 2.05
    sill: float = 0.0  # height above the floor (windows)
    material: str = "wood"
    connects_to: str | None = None
    # Vertical circulation: the floor below this opening (stairs only).
    rises_to_floor: int | None = None


class OutdoorArea(BaseModel):
    id: str = Field(default_factory=lambda: _id("out"))
    name: str = "garden"
    kind: Literal["garden", "terrace", "pool", "courtyard", "deck", "driveway"] = "garden"
    position: Vec3 = Field(default_factory=Vec3)
    dimensions: Dimensions = Field(default_factory=Dimensions)
    material: str = "grass"


class BuildingBlock(BaseModel):
    """BLOCK 1 - building, design and spaces."""

    category: BuildingCategory = BuildingCategory.HOUSE
    style: ArchitecturalStyle = ArchitecturalStyle.MODERN
    site_shape: Literal["rectangle", "l_shape", "u_shape", "circular", "irregular"] = "rectangle"
    floors: int = 1
    exterior_material: str = "concrete"
    interior_material: str = "plaster"
    roof_type: Literal["flat", "gable", "hip", "shed", "dome"] = "flat"
    rooms: list[Room] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    outdoor_areas: list[OutdoorArea] = Field(default_factory=list)
    notes: str = ""

    @property
    def footprint(self) -> Dimensions:
        if not self.rooms:
            return Dimensions(width=10, height=3, depth=10)
        ground = [r for r in self.rooms if r.floor == 0] or self.rooms
        max_x = max(r.position.x + r.dimensions.width for r in ground)
        max_z = max(r.position.z + r.dimensions.depth for r in ground)
        min_x = min(r.position.x for r in ground)
        min_z = min(r.position.z for r in ground)
        height = max(r.position.y + r.dimensions.height for r in self.rooms)
        return Dimensions(width=max_x - min_x, height=height, depth=max_z - min_z)

    @property
    def total_floor_area(self) -> float:
        return sum(r.dimensions.floor_area for r in self.rooms)


class PlacedObject(BaseModel):
    """BLOCK 2 + BLOCK 3 - an object and its placement/behaviour."""

    id: str = Field(default_factory=lambda: _id("obj"))
    name: str
    category: Literal[
        "furniture", "appliance", "decor", "fixture", "component", "character", "light"
    ] = "furniture"
    room_id: str | None = None
    position: Vec3 = Field(default_factory=Vec3)
    rotation: Vec3 = Field(default_factory=Vec3)  # degrees
    scale: Vec3 = Field(default_factory=lambda: Vec3(x=1, y=1, z=1))
    dimensions: Dimensions = Field(default_factory=Dimensions)
    material: Material = Field(default_factory=Material)
    quantity: int = 1
    appearance: str = ""
    behaviors: list[str] = Field(default_factory=list)
    interactions: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    relationship: str | None = None  # e.g. "on:table_1", "against:north_wall"


class BuildingSpec(BaseModel):
    """Complete architectural specification: the three blocks."""

    request: str = ""
    title: str = "Untitled building"
    block1: BuildingBlock = Field(default_factory=BuildingBlock)
    block2: list[PlacedObject] = Field(default_factory=list)
    block3: list[PlacedObject] = Field(default_factory=list)
    lighting: list[dict[str, Any]] = Field(default_factory=list)
    environment: dict[str, Any] = Field(default_factory=dict)
    narrative: str = ""

    @property
    def all_objects(self) -> list[PlacedObject]:
        return [*self.block2, *self.block3]

    def room_by_id(self, room_id: str) -> Room | None:
        return next((r for r in self.block1.rooms if r.id == room_id), None)
