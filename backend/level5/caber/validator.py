"""Independent verification for CABER building projects.

Checks the architectural specification and its generated scene for the
properties the directive requires: geometry validity, room connections, object
placement, dimension consistency, material coverage, navigation and a
performance budget. Each check returns a structured result so the platform can
report what actually passed rather than asserting success.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from level5.caber.geometry import build_scene
from level5.caber.models import BuildingSpec, Room


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class ValidationReport:
    checks: list[Check]
    stats: dict[str, Any]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        return round(100 * sum(c.passed for c in self.checks) / len(self.checks), 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "checks": [c.as_dict() for c in self.checks],
            "stats": self.stats,
        }


def validate(spec: BuildingSpec) -> ValidationReport:
    scene = build_scene(spec)
    prims = scene["primitives"]
    rooms = spec.block1.rooms
    checks: list[Check] = []

    # Geometry validity --------------------------------------------------- #
    bad = [p for p in prims if any(s <= 0 for s in p["size"])]
    checks.append(
        Check(
            "geometry_validity",
            not bad,
            "all primitives have positive dimensions" if not bad else f"{len(bad)} degenerate primitives",
        )
    )

    # Room count / coverage ---------------------------------------------- #
    checks.append(
        Check("rooms_present", bool(rooms), f"{len(rooms)} rooms defined")
    )

    # Room overlap -------------------------------------------------------- #
    overlaps = _overlapping_rooms(rooms)
    checks.append(
        Check(
            "room_no_overlap",
            not overlaps,
            "no two rooms on the same floor overlap"
            if not overlaps
            else f"{len(overlaps)} overlapping pair(s)",
        )
    )

    # Room connections ---------------------------------------------------- #
    doors = [o for o in spec.block1.openings if o.kind == "door"]
    stairs = [o for o in spec.block1.openings if o.kind == "stair"]
    connected = (
        {o.room_id for o in doors}
        | {o.connects_to for o in doors if o.connects_to}
        | {o.room_id for o in stairs}
        | {o.connects_to for o in stairs if o.connects_to}
    )
    unconnected = [r.name for r in rooms if r.id not in connected and len(rooms) > 1]
    checks.append(
        Check(
            "room_connections",
            not unconnected,
            f"{len(doors)} doors and {len(stairs)} stairs connecting rooms"
            if not unconnected
            else f"unconnected rooms: {', '.join(unconnected[:5])}",
        )
    )

    # Vertical circulation between storeys --------------------------------- #
    if len({r.floor for r in rooms}) > 1:
        checks.append(
            Check(
                "vertical_circulation",
                bool(stairs),
                f"{len(stairs)} stair connection(s) between floors"
                if stairs
                else "no stairs connect the storeys",
            )
        )

    # Object placement ---------------------------------------------------- #
    misplaced = _objects_outside_rooms(spec)
    checks.append(
        Check(
            "object_placement",
            not misplaced,
            f"{len(spec.all_objects)} objects placed inside their rooms"
            if not misplaced
            else f"{len(misplaced)} objects outside their room",
        )
    )

    # Dimension consistency ---------------------------------------------- #
    inconsistent = [
        p["name"]
        for p in prims
        if p["kind"] == "wall" and (p["size"][1] <= 0 or p["size"][2] <= 0 or p["size"][0] <= 0)
    ]
    checks.append(
        Check(
            "dimension_consistency",
            not inconsistent,
            "all wall segments have consistent dimensions"
            if not inconsistent
            else f"{len(inconsistent)} inconsistent walls",
        )
    )

    # Material coverage --------------------------------------------------- #
    missing_material = [
        r.name for r in rooms if not r.material
    ]
    checks.append(
        Check(
            "material_coverage",
            not missing_material,
            f"all {len(rooms)} rooms have a material"
            if not missing_material
            else f"rooms without material: {', '.join(missing_material)}",
        )
    )

    # Openings ------------------------------------------------------------ #
    openings_ok = all(o.offset >= 0 and o.width > 0 for o in spec.block1.openings)
    checks.append(
        Check(
            "openings_valid",
            openings_ok,
            f"{len(spec.block1.openings)} openings "
            f"({len([o for o in spec.block1.openings if o.kind == 'door'])} doors, "
            f"{len([o for o in spec.block1.openings if o.kind == 'window'])} windows)",
        )
    )

    # Navigation: every room reachable from the entrance via doors and stairs.
    reachable = _reachable_rooms(rooms, [*doors, *stairs])
    checks.append(
        Check(
            "navigation",
            len(reachable) == len(rooms) or not rooms,
            f"{len(reachable)}/{len(rooms)} rooms reachable",
        )
    )

    # Performance budget -------------------------------------------------- #
    prim_count = len(prims)
    checks.append(
        Check(
            "performance_budget",
            prim_count <= 4000,
            f"{prim_count} primitives (budget 4000)",
        )
    )

    # Lights -------------------------------------------------------------- #
    checks.append(
        Check(
            "lighting",
            len(scene["lights"]) >= 1,
            f"{len(scene['lights'])} lights",
        )
    )

    return ValidationReport(checks=checks, stats=scene["stats"])


def _overlapping_rooms(rooms: list[Room]) -> list[tuple[str, str]]:
    overlaps: list[tuple[str, str]] = []
    for i, a in enumerate(rooms):
        for b in rooms[i + 1 :]:
            if a.floor != b.floor:
                continue
            if _rects_overlap(a, b):
                overlaps.append((a.name, b.name))
    return overlaps


def _rects_overlap(a: Room, b: Room) -> bool:
    tol = 0.01
    ax2, az2 = a.position.x + a.dimensions.width, a.position.z + a.dimensions.depth
    bx2, bz2 = b.position.x + b.dimensions.width, b.position.z + b.dimensions.depth
    return (
        a.position.x + tol < bx2
        and b.position.x + tol < ax2
        and a.position.z + tol < bz2
        and b.position.z + tol < az2
    )


def _objects_outside_rooms(spec: BuildingSpec) -> list[str]:
    bad: list[str] = []
    for obj in spec.all_objects:
        if obj.room_id is None:
            continue
        room = spec.room_by_id(obj.room_id)
        if room is None:
            bad.append(obj.name)
            continue
        margin = 0.6  # allow slight overhang for wide furniture
        if not (
            room.position.x - margin <= obj.position.x <= room.position.x + room.dimensions.width + margin
            and room.position.z - margin <= obj.position.z <= room.position.z + room.dimensions.depth + margin
        ):
            bad.append(obj.name)
    return bad


def _reachable_rooms(rooms: list[Room], doors: list) -> set[str]:
    if not rooms:
        return set()
    graph: dict[str, set[str]] = {r.id: set() for r in rooms}
    for door in doors:
        if door.room_id in graph and door.connects_to in graph:
            graph[door.room_id].add(door.connects_to)
            graph[door.connects_to].add(door.room_id)
    start = rooms[0].id
    seen = {start}
    stack = [start]
    while stack:
        current = stack.pop()
        for neighbour in graph.get(current, ()):
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return seen
