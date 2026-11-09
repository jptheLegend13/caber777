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

This run completed with an **honest failure** and is reported as such:

```
status: failed
  task_succeeded  Architecture, data model, API contract, design-token spec
  task_succeeded  PostgreSQL schema, ORM models, and Alembic migrations
  task_succeeded  Original design system: tokens and component library
  task_failed     Authentication, JWT tokens, RBAC, and audit logging
                  -> agent conversation ended in error
  task_skipped    Task CRUD, assignment, and analytics API endpoints (x5 dependents)
  task_skipped    Security review, test suite, CI, review (blocked upstream)
```

The failing task's agent conversation ended in an error (the shared model
gateway returned HTTP 504, `Agent run timed out`, under load). Eight dependent
tasks were marked `skipped` with reason "blocked by an upstream failure" rather
than being run anyway or marked done. The project status is `failed`. No task
was recorded as successful without evidence.

Two real defects this run exposed, both fixed afterwards with tests:

1. **Verification marked all 9 criteria satisfied** even though the project
   failed. The old code fell back to "any succeeded task owns this criterion".
   `_verify` now matches each criterion to the task that actually produces it,
   excludes review-only roles from owning criteria, and leaves an unaddressed
   criterion unsatisfied with evidence "no task produced evidence for this
   criterion".
2. **A task had no retry path.** A transient gateway timeout failed the task
   permanently. Tasks now carry `max_attempts` (default 2) and retry with
   exponential backoff *only* for transient infrastructure faults (504/502/503,
   timeouts, rate limits, connection errors), never for the agent's own failures
   (failed tests, syntax errors, assertion errors). Retrying a real defect would
   burn budget and hide the defect.

Artifacts the run did produce before failing (160+ real files), including:

```
docs/architecture.md, docs/api-contract.md, docs/design-tokens.md, docs/tokens.json
backend/alembic/versions/000{1..4}_*.py, backend/alembic.ini, backend/app/{db,models,seed}.py
frontend/src/components/ui/{Button,Input,Textarea,Badge,Spinner,Toast,Tooltip,ThemeProvider}.tsx
frontend/src/design/tokens.ts, frontend/src/styles/{tokens,global}.css
frontend/tailwind.config.ts, frontend/postcss.config.js, frontend/tsconfig.*.json
scripts/gen_tokens.py, scripts/validate_spec.py
```

A re-run of this acceptance request on the corrected code is the outstanding
item; it is listed as not done rather than claimed.

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

## Run 5 — final capability audit (this cycle)

Live re-verification of each CABER intelligence and the platform fixes, against
the running backend (`:12000`) and Agent Server (`:60000`). Every item below was
observed this cycle, not carried over from a previous one.

| Check | Method | Result |
|---|---|---|
| CABER building (Intelligence C) | `GET /api/projects/proj_c7c9a0431af6/caber/{spec,validation,viewer}` | Villa spec: 11 rooms, 56 objects, 35 openings, 2 floors; validation 12/12, score 100.0, 255 primitives; viewer 200, 85 KB |
| CABER validation survives restart (F11) | fresh backend on `:12099`, then `GET /caber/validation` | 200 with the persisted report (was 404 before the fix) |
| Problem-solving (Intelligence B) | M/M/1 queue project `proj_20f47c55b319` | `delivered`; `solution.json` with restatement, approach and computation |
| Innovation pipeline (§13) | `POST /api/innovate` (self-tuning cache) | `delivered`; `innovation.json` + `prototype.py`; confidence **low**, feasibility **uncertain**, with four explicit limitations (3 seeds, no significance test, LRU-only baseline, small stationary traces) |
| Application creation (Intelligence A) | enterprise task-manager run `proj_6128c135609c` | 3/10 tasks succeeded so far; backend task conversation live and `running` on the Agent Server |
| Event pagination (F5) | `get_all_events` over the 8 busiest conversations | 592, 374, 191, 152 … events walked with **zero duplicate ids** |
| Per-task worktree isolation (F3) | real agent conversation, `LEVEL5_TASK_WORKTREES=1` | agent ran in `.level5-worktrees/<task>`; `hello.txt` merged into the shared workspace and committed; worktree removed |
| Agent registry | `GET /api/agents` | 38 roles across 6 disciplines (software 12, ai 6, graphics 6, quality 6, leadership 4, research 4) |
| Provider adapters | `GET /api/providers` | openhands (managed, available), openai, anthropic, google, and open-weight/local entries |
| Benchmark suite | `GET /api/benchmarks/suite{,/results}` | suite v1.0.0 defined; results **empty** — no run recorded, and missing runs are not scored as passes or failures |

Honest status: the enterprise task-manager run is still in progress and is **not
delivered**. No cross-system benchmark has been run.

## Test suite

```
cd backend && .venv/bin/python -m pytest -q
204 passed
```

Coverage: domain model and storage, agent registry (38 roles), CABER geometry
and validation, orchestrator scheduling and failure propagation, per-task
worktree isolation (including the real merge-conflict fallback), honest
acceptance-criteria verification, self-improvement screening, real
problem-solver code execution, event paging, and API integration. The only
network boundary replaced in any test is the Agent Server client in the
orchestrator tests, and that test module says so.

---

## Acceptance run — enterprise task-management application

Request (Section 21): "Build an enterprise-grade task-management application
with an original premium UI/UX, responsive frontend, backend, authentication,
database, task management, user roles, analytics, API documentation and
automated tests."

The run is executed against the live model gateway and a real Agent Server.
Findings from it, in order:

### Run 1 — failed, cause hidden

Reported only "agent conversation ended in error"; the project failed with 0/8
criteria satisfied. Root cause was not visible.

**Defect.** `collect_result` read only the first 100 events. The terminal
`ConversationErrorEvent` is emitted last, so it was never seen. The true cause
was `MaxIterationsReached` — the agent hit the 120-iteration ceiling mid-task
after doing real work — and the server had already classified it
`retryable: false`, which the code could not read.

### Run 2 — failed, real cause visible

After the fix the error surfaced correctly as `MaxIterationsReached`, and the
iteration ceiling was raised to 400 (a task that scaffolds a whole application
needs well over a hundred tool calls).

Three further defects were found while watching this run:

- **Truncated evidence.** The events search endpoint returns one page and
  exposes no cursor — only `timestamp__gte`. Reading the first 100 events
  missed most actions. `get_all_events` now pages on the last event's
  timestamp. Verified against a live conversation: 573 events, 187 iterations
  and 52 files, against ~30 and a handful before.
- **Wrong argument location.** `file_editor` puts `path`/`command` at the top of
  `action`; `terminal` nests them under `args`. Reading only `args` recorded
  almost no files, so the artifact list was near-empty.
- **Dependencies counted as deliverables.** An agent running `npm install`
  created 15k files, all recorded as artifacts. `node_modules`, `.venv`, `dist`,
  `build`, `target` and similar are now excluded; they stay in the workspace.
- **Delivery not gated on the specification.** A run was marked `delivered`
  whenever no task failed, even with zero acceptance criteria met. Unmet
  criteria now fail the project.

### Run 3 — resumed, then build-verified

The run was interrupted by a backend restart. Resume had a defect of its own:

- **Resume silently restarted.** `_run_full_pipeline` always re-planned, which
  builds a fresh task graph and discards every completed task, its evidence and
  its artifacts. `prepare_resume` now keeps succeeded tasks and resets a task
  caught mid-flight to PENDING. Verified live: after a restart the completed
  scaffold task was preserved and the two in-flight tasks resumed as attempt 2.

Running the generated app's real build then showed the front end **does not
compile** (TS2345, TS1005 and similar), and the generated monorepo has a real
structure (`apps/web`, `apps/api`, root workspace scripts). A failing build is
now repaired, not just reported: a bounded build → repair → rebuild cycle
(`LEVEL5_MAX_BUILD_REPAIRS`, default 2) hands the compiler output to a
`debugging_engineer` conversation whose prompt forbids disabling type checking,
removing tests or loosening the build to force a pass.

**Honest status:** the acceptance project reaches a real 11-task graph executed
by domain-appropriate specialists (scaffold, database, security, backend,
analytics, UI/UX, frontend, API, tests, CI, review), producing a real monorepo
with a working `npm install` and a real build. The front end did **not** build
on the recorded run; that is a real defect, and the repair loop that addresses
it is new and has not yet been exercised on a full run. This is not a delivered
enterprise application yet.

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
