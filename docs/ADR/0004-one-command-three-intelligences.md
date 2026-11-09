# ADR 0004 — One command interface, three intelligences

- **Status:** Accepted
- **Date:** 2026-11-08
- **Context:** The directive (§3, §12) requires one command box that routes to
  three specialised CABER intelligences (A: application creation, B: problem
  solving, C: building creation) over shared infrastructure. Until this cycle the
  dedicated `/solve`, `/innovate` and `/caber/buildings` endpoints existed, but
  the main product surface — `POST /api/projects/{id}/run` — always planned a
  generic engineering task graph. A building request or a novel-idea request
  therefore never reached its specialist engine: the architecture was documented
  but not wired end to end (audit finding F7).

## Decision

Route on the **classified CABER module**, not on a request-parsing heuristic, at
a single dispatch point in `_run_full_pipeline`:

1. Split the orchestrator's `understand_and_plan` into `understand()` and
   `plan()`, so the run pipeline can inspect the specification between the two.
2. After `understand()`, dispatch:
   - `caber_module == "C"` → `CABERBuildingService.build(project)`.
   - `caber_module == "B"` and the request reads as a novel/untested idea →
     `innovate_project(project)`.
   - everything else → `plan()` then `execute()` (the task graph).

The building/innovation engines own their project status and artifacts; the
pipeline persists the returned project. An existing plan is always resumed
rather than re-planned, so routing never discards recorded work.

## Rationale

- The module classification is produced by Central Intelligence from the user's
  own words, so routing follows understanding rather than a brittle keyword list.
- A small `_looks_like_innovation` heuristic only decides **between** two
  problem-solving paths (innovation vs. generic research); both are valid, so a
  misroute degrades gracefully instead of failing.
- One dispatch point keeps the "one command interface" promise and is covered by
  `tests/test_routing.py`.

## Consequences

- The command box now reaches all three intelligences; a single run still spans
  one intelligence (multi-intelligence runs remain future work, Milestone 6).
- New specialist engines must be reachable from this dispatch point to be part of
  the product, not just an endpoint.
