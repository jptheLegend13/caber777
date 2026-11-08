"""Tests for CABER building intelligence: spec, geometry and validation."""

from __future__ import annotations

from level5.caber.geometry import build_scene
from level5.caber.models import (
    BuildingBlock,
    BuildingSpec,
    Dimensions,
    Opening,
    PlacedObject,
    Room,
    Vec3,
)
from level5.caber.validator import validate


def _two_storey_spec() -> BuildingSpec:
    """A small, valid two-storey building used across the tests."""
    rooms = [
        Room(name="Living", purpose="living", floor=0,
             position=Vec3(x=0, y=0, z=0), dimensions=Dimensions(width=6, height=2.8, depth=5)),
        Room(name="Kitchen", purpose="kitchen", floor=0,
             position=Vec3(x=6, y=0, z=0), dimensions=Dimensions(width=4, height=2.8, depth=5)),
        Room(name="Bedroom", purpose="bedroom", floor=1,
             position=Vec3(x=0, y=3.0, z=0), dimensions=Dimensions(width=6, height=2.8, depth=5)),
    ]
    block = BuildingBlock(rooms=rooms, floors=2)
    block.openings = [
        Opening(kind="door", room_id=rooms[0].id, connects_to=rooms[1].id, wall="east", offset=2.0),
        Opening(kind="stair", room_id=rooms[2].id, connects_to=rooms[0].id, wall="south", offset=0.5, rises_to_floor=1),
    ]
    spec = BuildingSpec(title="Test building", block1=block)
    spec.block2 = [
        PlacedObject(name="Sofa", room_id=rooms[0].id, position=Vec3(x=1, y=0, z=1),
                     dimensions=Dimensions(width=2, height=0.8, depth=0.9)),
    ]
    return spec


class TestGeometry:
    def test_scene_has_required_keys(self):
        scene = build_scene(_two_storey_spec())
        for key in ("primitives", "lights", "bounds", "stats", "metadata"):
            assert key in scene

    def test_all_primitives_have_positive_size(self):
        scene = build_scene(_two_storey_spec())
        assert scene["primitives"]
        for prim in scene["primitives"]:
            assert all(s > 0 for s in prim["size"]), prim

    def test_floors_and_walls_generated(self):
        scene = build_scene(_two_storey_spec())
        kinds = {p["kind"] for p in scene["primitives"]}
        assert "floor" in kinds
        assert "wall" in kinds
        assert "roof" in kinds

    def test_objects_are_placed(self):
        scene = build_scene(_two_storey_spec())
        assert any(p["kind"] == "furniture" for p in scene["primitives"])

    def test_bounds_are_finite_and_sized(self):
        scene = build_scene(_two_storey_spec())
        bounds = scene["bounds"]
        assert all(isinstance(v, (int, float)) for v in bounds["size"])
        assert bounds["size"][0] > 0 and bounds["size"][1] > 0 and bounds["size"][2] > 0

    def test_door_opening_splits_wall(self):
        """A door on a wall must not leave that wall as a single slab."""
        spec = _two_storey_spec()
        scene = build_scene(spec)
        living_id = spec.block1.rooms[0].id
        living_walls = [
            p for p in scene["primitives"]
            if p["kind"] == "wall" and p["room_id"] == living_id
            and abs(p["size"][0] - 0.2) < 1e-6  # east wall is thin in x
        ]
        assert len(living_walls) >= 2, "expected the east wall to be split around the door"


class TestValidation:
    def test_valid_spec_passes_all_checks(self):
        report = validate(_two_storey_spec())
        failed = [c.name for c in report.checks if not c.passed]
        assert not failed, f"unexpected failures: {failed}"
        assert report.passed is True
        assert report.score == 100.0

    def test_overlapping_rooms_are_detected(self):
        spec = _two_storey_spec()
        spec.block1.rooms.append(
            Room(name="Clash", purpose="storage", floor=0,
                 position=Vec3(x=1, y=0, z=1), dimensions=Dimensions(width=3, height=2.8, depth=3))
        )
        report = validate(spec)
        overlap = next(c for c in report.checks if c.name == "room_no_overlap")
        assert overlap.passed is False

    def test_missing_stairs_are_detected(self):
        spec = _two_storey_spec()
        spec.block1.openings = [o for o in spec.block1.openings if o.kind != "stair"]
        report = validate(spec)
        circulation = next(c for c in report.checks if c.name == "vertical_circulation")
        assert circulation.passed is False

    def test_misplaced_object_is_detected(self):
        spec = _two_storey_spec()
        spec.block2.append(
            PlacedObject(name="Far away", room_id=spec.block1.rooms[0].id,
                         position=Vec3(x=500, y=0, z=500),
                         dimensions=Dimensions(width=1, height=1, depth=1))
        )
        report = validate(spec)
        placement = next(c for c in report.checks if c.name == "object_placement")
        assert placement.passed is False

    def test_report_serialises(self):
        data = validate(_two_storey_spec()).as_dict()
        assert set(data) == {"passed", "score", "checks", "stats"}
        assert isinstance(data["checks"], list)
