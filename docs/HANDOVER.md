# LEVEL 5 — release candidate handover

**Version:** `0.1.0` · **Branch:** `caber` · **Tag:** `v0.1.0-rc1`

This is the operator's guide to running and understanding the release candidate.
It states what is verified and what is not. The detailed evidence lives in
`RUNS.md`; the milestone state lives in `ROADMAP.md`; the security pass lives in
`SECURITY.md`.

---

## 1. What this is

LEVEL 5 is an autonomous engineering platform. You describe a result in plain
text or voice; it produces a structured specification, researches it, plans a
dependency-aware task graph, allocates specialist agents, and executes real work
through the OpenHands Agent Server — writing files, running commands and running
tests in a sandboxed workspace. Three specialised intelligences share one
platform:

- **A — Application Creation:** software, apps, APIs, databases, AI systems.
- **B — Problem Solving:** research, models, simulations, verification.
- **C — Building Creation (CABER):** architecture, 3D environments, objects.

## 2. Running it

```bash
# one-time setup
scripts/setup.sh

# start backend (and the frontend dev server with --frontend)
scripts/dev.sh --frontend

# health check
curl -sS http://127.0.0.1:12000/api/health
```

The backend needs a reachable OpenHands Agent Server and its session key
(`LEVEL5_AGENT_SERVER_URL`, `SESSION_API_KEY`). The frontend is served on
`http://localhost:5173` in dev, or built to `frontend/dist` for production.

## 3. Using it

Type or speak a request into the command box. Examples that are routed to the
three intelligences automatically:

- "Build a complete web application with frontend, backend and tests." → A
- "Investigate this unsolved problem and build an experimental solution." → B
- "Design a modern lakeside house and let me walk through it." → C
- "Build an app that displays a 3D building." → C then A (handoff)

The workspace shows the current request, requirements, research, agent activity,
execution progress, files, deliverables, live preview, test results, errors,
version history and the final report. Every control performs its function.

## 4. Verified in this release candidate

Live evidence (see `RUNS.md` Run 7 for the raw observations):

- End-to-end creation of a real deliverable — a Python CLI (`wordcount`):
  8/8 tasks, 5/5 acceptance criteria, 14/14 tests, status `delivered`; the tool
  was then run directly and behaves correctly, including the error path.
- Persistence across a backend restart — the project reloaded intact.
- Defect detection and repair — a controlled regression was caught by the
  project's tests and repaired through the platform's own follow-up path.
- Research retrieval with no API key — 8 sources merged across 5 providers.
- Backend suite: **252 passed**. Frontend typecheck and build: **pass**.

## 5. Not verified — do not claim

- **No competitive benchmark has been run.** No superiority claim is made
  anywhere. The suite exists but no external system has been run against it.
- **Mobile/desktop preview** is an artifact summary, not a device emulator.
- **CABER geometry is box-based** (Three.js). It is a real interactive viewport,
  not a match for Unreal Engine / Blender / Houdini.
- **No physical manufacturing or structural certification.**
- One **accepted dependency risk** (`filelock`) is documented in `SECURITY.md`.

## 6. Where things are

| Area | Path |
| --- | --- |
| Backend (FastAPI, OpenHands SDK) | `backend/level5/` |
| Frontend (React + TS + Three.js) | `frontend/src/` |
| Tests | `backend/tests/` |
| Roadmap / evidence / security | `docs/ROADMAP.md`, `docs/RUNS.md`, `docs/SECURITY.md` |
| Decisions | `docs/ADR/` |

## 7. Next work

See `ROADMAP.md`. The largest outstanding items are: run the competitive
benchmark suite against a real external system under equivalent conditions;
extend verified execution coverage beyond the web domain; and lift the
`filelock` constraint when the OpenHands SDK allows it.
