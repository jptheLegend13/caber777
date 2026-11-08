# ADR 0003 — CABER building generation: procedural geometry from a three-block spec

- **Status:** Accepted
- **Date:** 2026-11-08

## Decision

Represent a building as a **three-block specification** (`backend/level5/caber/models.py`)
and generate geometry procedurally from it (`geometry.py`):

- **Block 1** — building, design and spaces: category, style, floors, rooms
  (name, purpose, dimensions, position), openings, outdoor areas, materials.
- **Block 2** — objects and components: furniture, appliances, decor, fixtures,
  architectural components and characters, each with dimensions, materials,
  appearance and quantity.
- **Block 3** — position, actions and behaviours: coordinates, rotation, scale,
  relationships, interactions, states, events, triggers.

Geometry is a flat list of transformed box primitives with PBR material
parameters, plus a lighting rig and scene bounds. Openings are realised by
splitting each wall into solid segments around doors and windows, so the
geometry stays watertight without CSG.

Vertical circulation is generated automatically: each upper storey is linked to
the room below it by a stair connection, rendered as a flight of steps.

Outputs per project: `building.spec.json`, `building.scene.json`,
`validation.json` and a self-contained `viewer.html` (Three.js).

## Rationale

- The directive requires the three specification blocks to **control the actual
  3D project**. Generating from the spec makes that literal: change the spec,
  the scene changes.
- A renderer-agnostic primitive list lets the same scene drive the in-app
  Three.js viewport, the standalone viewer, and — later — an offline renderer or
  glTF/USD export, without rewriting the generation logic.
- Wall segmentation avoids a CSG dependency and keeps geometry verifiable.

## Verification

`backend/level5/caber/validator.py` independently checks geometry validity, room
overlap, room connections, vertical circulation, object placement, dimension
consistency, material coverage, opening validity, reachability, a primitive
budget and lighting. The validator is run on every build and its score is shown
in the UI and stored as `validation.json`.

## Consequences and limits

- The renderer is Three.js in the browser. This is a real interactive viewport,
  but it is **not** claimed to match Unreal Engine, Blender or Houdini output.
  The directive explicitly forbids claiming to beat those without
  equivalent-condition benchmarks; none have been run.
- Geometry is box-based. Sloped roofs are approximated by rotated slabs and
  domes by a single box. Curved and sculpted forms would need a mesh kernel
  (OpenUSD / IFC / a CSG library) — a future ADR.
