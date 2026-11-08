# AGENTS.md — repository memory for LEVEL 5

Persistent, repository-specific knowledge. Read this before working in this repo.

## What this repository is

**LEVEL 5** — an autonomous universal engineering and creation platform. A user
describes an intended result in text or voice; the platform understands it,
researches it, produces a structured specification, plans a dependency-aware
task graph, allocates specialist agents, executes real work in a sandboxed
workspace, tests it, reviews it, repairs defects and delivers artifacts.

Three CABER intelligences share one platform:

| Module | Name | Code |
|---|---|---|
| A | Application Creation | `backend/level5/orchestrator.py` + `agents/registry.py` |
| B | Problem Solving | `backend/level5/intelligence/problem_solving.py` + `research.py` |
| C | Building Creation | `backend/level5/caber/` |
| P | Shared platform | `api/`, `storage/`, `llm/`, `runtime/`, `events.py` |

## Layout

```
backend/level5/
  config.py            env-driven settings (pydantic-settings)
  models.py            domain model: Project, Specification, Task, TaskGraph, …
  events.py            in-process pub/sub bus for SSE streaming
  orchestrator.py      understand → plan → execute → verify → deliver
  agents/registry.py   38 specialist roles, 6 disciplines
  intelligence/        understanding.py, planner.py, research.py, problem_solving.py
  caber/               models.py (3 blocks), architect.py, geometry.py, validator.py, service.py
  llm/client.py        provider-agnostic OpenAI-compatible client
  runtime/agent_server.py  Agent Server REST client
  storage/store.py     SQLite + JSON project store
  api/                 app.py (FastAPI), routes.py (REST + SSE)
frontend/src/          React + TypeScript workspace (App.tsx, Viewport.tsx, useVoiceInput.ts)
docs/ADR/              architecture decision records
docs/ROADMAP.md        milestone status
```

## How to run

```bash
# Backend (needs the Agent Server reachable)
cd backend
.venv/bin/python -m uvicorn level5.api.app:app --host 0.0.0.0 --port 12000

# Tests
.venv/bin/python -m pytest tests/ -q

# Frontend
cd frontend && npm run dev     # or: npm run build  (backend serves dist/)
```

The session key for the local Agent Server is at `~/.oh_session_key`
(chmod 600). Do not print it.

## Environment facts (verified in this environment)

- Agent Server: `http://127.0.0.1:60000`, OpenHands Agent Server v1.60.1,
  SDK 1.60.1. Health check: `GET /` returns 200.
- The Agent Server exposes an OpenAI-compatible gateway at `/v1`; the default
  model id is `openhands_Default` and it authenticates with the session key.
- Python 3.13; the venv is `backend/.venv` (uv-managed). `openhands-sdk` and
  `openhands-tools` are pinned to the **same** version (1.60.1).
- Node 24 / npm 11; frontend build output is `frontend/dist`.
- **pydantic must float** (`pydantic>=2.13.5`): the SDK requires it, and pinning
  an older version breaks resolution.

## Conventions and invariants

- **Never fabricate results.** Task outcomes, test results, research sources and
  validation scores come from real execution or real retrieval. Failures are
  recorded verbatim.
- **Separate user requirements from inferred decisions** (`Requirement.origin`).
- **A feature is complete only when its verification passes.** Run the tests.
- **No competitive superiority claims** without equivalent-condition benchmarks.
- Agents must not overwrite each other's files without coordination; the
  orchestrator runs dependency-ordered batches.
- Secrets stay on the backend. Never put credentials in frontend code.
- Prefer the real code path in tests over mocks; replace only the network
  boundary when necessary, and say so.

## Gotchas

- `TaskGraph.ready()` returns tasks whose dependencies all **succeeded**. A
  failed dependency causes its dependents to be skipped, not run.
- CABER walls are split into solid segments around openings rather than cut with
  CSG, so the geometry stays watertight without extra dependencies.
- The `preview` tab only appears for CABER (module C) projects.
- SQLite is used for local persistence; `LEVEL5_DATA_DIR` overrides the data
  directory (tests point it at a tmp dir).
