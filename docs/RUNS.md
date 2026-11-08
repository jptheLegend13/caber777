# Verified runs and measured evidence

This file records what was actually executed and observed, with real numbers.
It is the honest performance record for this build. Nothing here is projected,
estimated or aspirational, and **no comparison against another system is made**.

Environment for every run below:

| Item | Value |
|---|---|
| OpenHands Agent Server | v1.60.1 |
| OpenHands SDK / Tools | 1.60.1 / 1.60.1 (aligned) |
| Agent Server URL | `http://127.0.0.1:60000` |
| Model endpoint | Agent Server OpenAI-compatible gateway, model `openhands_Default` |
| Python / Node | 3.13 / 24 |
| Platform | LEVEL 5 backend on `:12000`, single machine |

---

## Run 1 — CABER Intelligence C (building creation)

Request: *"Design a modern two-storey villa with 3 bedrooms, a large open-plan
living room and kitchen, two bathrooms, a study, a terrace and a pool."*

Result: **validation score 100.0, passed = true, elapsed 116 s**

```
[PASS] geometry_validity       all primitives have positive dimensions
[PASS] rooms_present           10 rooms defined
[PASS] room_no_overlap         no two rooms on the same floor overlap
[PASS] room_connections        14 doors and 1 stairs connecting rooms
[PASS] vertical_circulation    1 stair connection(s) between floors
[PASS] object_placement        54 objects placed inside their rooms
[PASS] dimension_consistency   all wall segments have consistent dimensions
[PASS] material_coverage       all 10 rooms have a material
[PASS] openings_valid          33 openings (14 doors, 18 windows)
[PASS] navigation              10/10 rooms reachable
[PASS] performance_budget      239 primitives (budget 4000)
[PASS] lighting                7 lights
stats: rooms 10, objects 54, primitives 239, floor area 384.0, floors 2
```

An earlier run of the same request scored 90.9% and **failed** the navigation
check (the upper floor was unreachable). The cause was a real defect: no
vertical circulation was generated. Stairs were added to the model, the
architect and the geometry engine, and the validator's reachability traversal
was corrected to follow stairs as well as doors. This run is the re-verification
after that fix.

Viewport: `GET /api/projects/{id}/caber/viewer` returned HTTP 200 and the scene
rendered in a browser as an interactive Three.js canvas with object selection.

## Run 2 — CABER Intelligence B (problem solving)

Problem: compare one M/M/1 queue against four parallel M/M/1 queues for a
service at λ = 40 req/s and mean service time 12 ms.

Result: the engine wrote a Python model, **executed it** (exit code 0, 0.039 s)
and reported from the real output:

```
single M/M/1      : ρ=0.48,  L≈0.923, Wq≈11.1 ms
four parallel M/M/1: ρ=0.12/server, Wq≈1.64 ms
pooled M/M/4      : Wq≈0.061 ms
```

Notably, the engine's own limitations list caught that the four-queue layout is
not capacity-matched to the single server, and that its `L` figure is
per-server rather than whole-system — i.e. it critiqued its own framing rather
than presenting a flattering comparison. Confidence was reported as `medium`,
with closed-form-only validation stated explicitly.

## Run 3 — CABER Intelligence A (application creation), Section 21 acceptance

Request: *"Build an enterprise-grade task-management application with an
original premium UI/UX, responsive frontend, backend, authentication, database,
task management, user roles, analytics, API documentation and automated tests."*

**Understanding:** specification produced, 14 requirements, 9 acceptance
criteria, user requirements kept separate from inferred decisions.

**Planning:** 12 tasks, dependency-ordered, with these roles:

```
product_architect, database_engineer, backend_engineer ×2, ui_ux_engineer,
frontend_engineer ×2, api_engineer, testing_engineer, devops_engineer,
security_engineer, code_reviewer
```

**Execution:** real OpenHands agent conversations ran in the project workspace,
executing real terminal commands and writing real files. Observed live agent
activity included `pwd && ls -la`, `find . -maxdepth 3`, and `git status`, with
the agent working in `/workspace/.../projects/proj_bd6079fa3ead`.

Artifacts written by the agents at the time of writing (160+ files), including:

```
docs/architecture.md, docs/api-contract.md, docs/design-tokens.md, docs/tokens.json
backend/alembic/versions/000{1..4}_*.py, backend/alembic.ini, backend/app/{db,models,seed}.py
frontend/src/components/ui/{Button,Input,Textarea,Badge,Spinner,Toast,Tooltip,ThemeProvider}.tsx
frontend/src/design/tokens.ts, frontend/src/styles/{tokens,global}.css
frontend/tailwind.config.ts, frontend/postcss.config.js, frontend/tsconfig.*.json
scripts/gen_tokens.py, scripts/validate_spec.py
```

This run was still in progress when this record was written; the first three
tasks (architecture, database schema, design system) had succeeded and two
backend tasks were executing in parallel. Task outcomes are reported as they
actually occur — a task that fails is recorded as failed and its dependents are
skipped, never silently marked done.

## Run 4 — domain-planning coverage (planner probe)

Four distinct requests, planned end to end:

| Request | Domain | Module | Tasks | Distinct roles allocated |
|---|---|---|---|---|
| Cross-platform mobile fitness tracker | `mobile_app` | A | 12 | 8, incl. `mobile_engineer` |
| Multi-agent research assistant | `multi_agent_system` | A | 12 | 9, incl. `multi_agent_orchestration_engineer` |
| Linear-attention research + benchmark | `research` | B | 9 | 7, incl. `technology_research_agent`, `performance_engineer` |
| Multi-tenant SaaS billing on Kubernetes | `backend_api` | A | 12 | 11, incl. `cloud_engineer` |

Each plan produced a real dependency chain (e.g. the mobile plan: architecture →
backend API → mobile foundation → secure credential storage → offline sync
engine → native integrations).

## Test suite

```
cd backend && .venv/bin/python -m pytest -q
74 passed
```

Coverage: domain model and storage, agent registry (38 roles), CABER geometry
and validation, orchestrator scheduling and failure propagation, honest
acceptance-criteria verification, self-improvement screening, real
problem-solver code execution, and API integration. The only network boundary
replaced in any test is the Agent Server client in the orchestrator tests, and
that test module says so.

---

## What is deliberately not claimed

- No benchmark against Claude Code, Codex, Cursor, Devin, OpenHands, Antigravity
  or any other system has been run. Establishing one requires equivalent tasks,
  model and hardware; that work is listed as not started in `ROADMAP.md`.
- CABER's renderer is Three.js in the browser. It is a real interactive viewport.
  It is **not** claimed to match Unreal Engine, Blender or Houdini output.
- CABER produces designs and simulations. It does not manufacture anything and
  does not certify structural safety.
- Agent success rates depend on the model. Where a task failed, the failure is in
  the record above.
