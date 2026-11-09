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
  worktrees.py         per-task git worktree isolation (opt-in)
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

## Generated deliverables (notes relocated)

Notes about LEVEL 5's generated deliverable projects live in
`docs/GENERATED-DELIVERABLES-NOTES.md`. Those projects are under the
gitignored `backend/.level5-data/projects/`, so they are not part of this
repository; keep their notes out of this file.

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
- The model gateway can return HTTP 504 `Agent run timed out` under load. That
  is transient: tasks retry it. It is not a task defect, so do not "fix" a task
  because of it.
- Review-only roles never own an acceptance criterion. A reviewer task lists
  every criterion, so letting it be the evidence owner reports universal
  satisfaction without producing anything.
- Retry only transient faults. Retrying a failed test or a syntax error burns
  budget and hides the defect.
- The Agent Server serves one model gateway. Running a second long project
  concurrently with the first starves the gateway and produces 504s.
- **A method on `Orchestrator` must not share a name with an engine attribute.**
  A step named `research` shadowed `self.research` (the `ResearchEngine`) and
  broke every generic run with `'ResearchEngine' object is not callable`. The
  step is `run_research`; pinned by a regression test in
  `tests/test_orchestrator.py`.
- Routing runs **before** generic research: `_run_full_pipeline` classifies the
  CABER module and dispatches buildings to `CABERBuildingService` and novel
  ideas to the innovation pipeline immediately, so a building request does not
  first burn minutes on web research. Only the generic path runs
  `run_research` → `plan` → `execute`.
- Attachments are read into request understanding: `_extract_text_excerpt` keeps
  a bounded text sample of text-like uploads, and any requirement it yields is
  tagged `origin: "user"` (never `inferred`). Uploads are stored under the
  project's `attachments/` dir with a sanitised basename, so a
  `../../etc/evil.txt` filename cannot escape.
- `LEVEL5_TASK_WORKTREES=1` isolates each task in its own git worktree
  (`level5/worktrees.py`). The project workspace is `git init`-ed on first use
  with a `.gitignore` for `node_modules/`, `dist/`, `.venv/` and friends; the
  branch is squash-merged back under a lock, and a conflict falls back to
  copying the task's changed files. Off by default; when isolation cannot be set
  up the task runs in the shared workspace and a `task_isolation` event says so.
- **The build test requires a *static* output dir.** `preview.find_dist()` only
  accepts `index.html` under `dist/`, `build/`, `out/`, or `.output/public/`. A
  default Next.js build emits only `.next/`, so `next build` exits 0 yet the
  harness appends `build exited 0 but produced no index.html` and fails the
  build test. A Next.js web app in this platform must therefore set
  `output: 'export'` (writes `out/`). Two consequences to plan for: (1) any
  dynamic route needs `generateStaticParams`, and (2) `next start` refuses an
  exported build — serve `out/` with a static server (see
  `frontend/scripts/serve-static.mjs`). Pinned by `tests/test_preview.py`.

## Session notes

- Verification honesty is enforced in `_verify`: a criterion is satisfied only
  when a succeeded non-review task actually addresses it. Pinned by
  `tests/test_verification.py`.
- Task retries are pinned by `tests/test_retries.py` (transient vs permanent).
- Real run outcomes, including failures, are recorded in `docs/RUNS.md`. Update
  it after any acceptance run rather than only noting successes.
- `docs/ROADMAP.md` uses `[x]` done, `[~]` partial, `[ ]` not started. Keep it
  accurate; the founder relies on it.
- The backend must be restarted to pick up code changes (uvicorn is not started
  with `--reload` in this environment).

## LEVEL 5 platform — operating notes (Phase 2 RC)

- **Run the platform:** `scripts/setup.sh` once, then `scripts/dev.sh --frontend`.
  Backend `127.0.0.1:12000`; Agent Server `127.0.0.1:60000` (SDK 1.60.1).
  Health: `curl -sS http://127.0.0.1:12000/api/health`.
- **Tests:** `cd backend && .venv/bin/python -m pytest -q` (252 passed).
  Frontend: `cd frontend && npx tsc --noEmit && npm run build`.
- **Hard rule (carried from Phase 1):** do NOT mark a feature done because code
  exists. Verify it live (run it, hit the endpoint, inspect the artifact) and
  record the raw observation in `docs/RUNS.md`.
- **Start a run:** `POST /api/projects {"request": "...", "auto_start": true}`.
  Watch `task_graph.tasks[].status`; `delivered` requires every acceptance
  criterion satisfied (unmet criteria fail the project, by design).
- **Repair an existing project:** `POST /api/projects/{id}/follow-up` drives the
  most recent agent conversation in the project workspace — the real repair path.
- **Per-project versioning:** each project workspace is its own git repo. Use
  `/revisions`, `/revisions/{sha}/diff`, `/revisions/{sha}/restore`,
  `/export` (zip). Restore commits a `pre-restore` revision first (reversible).
- **Research needs no key:** Wikipedia/arXiv/Crossref/GitHub/StackExchange always
  run; Tavily/Brave add coverage when their keys are set. The engine labels
  findings (`verified`/`published`/`hypothesis`/`unsupported`) and says so when
  retrieval finds nothing rather than inventing sources.
- **Dependency pin:** `openhands-sdk==1.60.1` → `litellm<1.106` →
  `filelock<4.0`. Do not upgrade `filelock` to 4.x; the resolution breaks. The
  accepted risk is documented in `docs/SECURITY.md`.
- **Docs map:** `docs/ROADMAP.md` (milestones + known limitations),
  `docs/RUNS.md` (live evidence per cycle), `docs/SECURITY.md`,
  `docs/HANDOVER.md`, `docs/ADR/`.

## LEVEL 5 intelligence independence (permanent requirement)

- **Rule:** LEVEL 5 must not depend on any one company's AI API. External model
  providers are optional development assistants, OFF by default
  (`LEVEL5_ALLOW_EXTERNAL_MODELS=0`). Never hard-code a provider; never fall
  back to an external model when the internal runtime fails.
- **The OpenHands dev gateway** (`LEVEL5_ALLOW_DEV_GATEWAY=1`, default on) is a
  DEVELOPMENT aid, not production inference. Set `=0` to drop the Agent Server
  transports entirely (the independence check does this).
- **Gateway:** `level5/llm/gateway.py` routes bare model calls by backend class
  (`internal` → `development` → `external`), capability and health. Internal is
  the production target; external is only chosen when no internal backend is
  configured AND the operator enabled external.
- **Self-hosted runtime:** `level5/llm/runtime.py` discovers/starts
  llama-server/vLLM/Ollama and keeps a model registry (`LEVEL5_LOCAL_MODELS_FILE`).
  It downloads nothing. Config: `LEVEL5_LOCAL_LLM_BASE_URL` (default
  `http://127.0.0.1:8080/v1`), `LEVEL5_LOCAL_LLM_MODEL`.
- **Memory:** `level5/knowledge/store.py` — SQLite + BM25, no model. The
  orchestrator writes spec/research to it and recalls it before planning.
  Endpoints: `GET /api/projects/{id}/memory[?q=]`.
- **Model-free core:** `level5/intelligence/fallbacks.py` — deterministic
  understanding + per-domain task-graph templates. Understanding/planning use
  them automatically when no model answers.
- **Verify independence:** `cd backend && .venv/bin/python scripts/independence_check.py`
  (9/9 expected). Tests: `tests/test_independence.py`. Posture: `GET /api/intelligence`.
- **Do not claim LEVEL 5 has its own foundation model.** None has been trained.
  A self-hosted third-party model is not "our model". Roadmap:
  `docs/ARCHITECTURE-INDEPENDENCE.md`.
