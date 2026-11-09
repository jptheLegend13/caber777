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

## Enterprise Task Manager (web_app) — persistence layer

The LEVEL 5 workspace also hosts the **Enterprise Task Manager** deliverable under
`.level5-data/projects/proj_bd6079fa3ead/`. Persistence lives in `backend/`:

- `app/db.py` — async engine/session factory. Reads `DATABASE_URL` from the
  environment (no hard-coded creds). `postgresql+asyncpg` (prod) or
  `sqlite+aiosqlite` (dev/test). Declarative `Base` + deterministic naming
  convention (`ck_`, `fk_`, `ix_`, `pk_`, `uq_`).
- `app/models.py` — SQLAlchemy 2.0 models: `roles`, `users`, `tasks`,
  `assignments`, `audit_log`, `refresh_tokens`. 26-char ULID text PKs, enums as
  `varchar` + CHECK, `timestamptz` (ISO text on SQLite), `citext` email on PG,
  JSONB tags/metadata. `AuditLog.event_metadata` maps to the `metadata` column
  (that attribute name is reserved on `DeclarativeBase`).
- `app/seed.py` — idempotent `seed_roles()` and `seed_admin()` (argon2id only).
- `alembic/versions/0001..0004` — initial schema, tasks/assignments, audit/tokens,
  guarded admin seed. `scripts/migrate.sh` wraps `alembic upgrade head`.
- `tests/test_schema_migrations.py` — applies the real migration chain to a
  throwaway PostgreSQL DB and asserts the live schema matches the models
  (columns, nullability, FKs + ondelete, indexes, CHECK/UNIQUE names), then
  downgrades to base. Skips unless `DATABASE_URL`/`TEST_DATABASE_URL` is a
  PostgreSQL URL with CREATEDB rights.

Run locally (test PostgreSQL on port 5433 in this sandbox):

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://taskmgr:testpw@127.0.0.1:5433/taskmgr \
  PYTHONPATH=. python -m pytest tests/ -q
```

Verify no drift after model changes: `alembic check` (must print
"No new upgrade operations detected").

## Enterprise Task Manager (web_app) — Meridian design system

The frontend (`frontend/`) implements the bespoke **Meridian** design system.
There is **no stock Tailwind theme**: `tailwind.config.ts` *replaces* (not
`extend`s) `colors`, `fontFamily`, `fontSize`, `spacing`, `borderRadius`,
`boxShadow`, `zIndex` and `screens` with values read directly from the generated
token module. A class not backed by a Meridian token simply does not exist.

- **Token source of truth** is `docs/tokens.json`; `scripts/gen_tokens.py`
  emits `frontend/src/design/tokens.{css,ts}`. **Do not hand-edit the generated
  files** — re-run the generator. `src/design/__tests__/theme.test.ts` asserts
  the generated module still deep-equals `docs/tokens.json`.
- **Theme layer**: `frontend/src/styles/tokens.css` holds shorthand aliases and
  the `[data-theme='dark']` remap of *semantic* tokens only; `global.css` holds
  base/reset, the `md-visually-hidden` and other utilities, and the
  `prefers-reduced-motion` kill-switch.
- **Import order matters** in `src/main.tsx`: `design/tokens.css` →
  `styles/tokens.css` → `styles/global.css`.
- **Component library**: `frontend/src/components/ui/` (Button, Input, Select,
  Textarea, Checkbox, Card/Panel, Badge/StatusBadge/PriorityBadge, Modal/
  ConfirmDialog, Table, Toast, Avatar, Tabs, EmptyState, Tooltip, Skeleton,
  Spinner, Icon, ThemeProvider) plus layout primitives in `ui/layout/`
  (Box, Container, Stack/Cluster/Spacer, Grid, Divider, PageHeader). Import from
  the barrel: `import { Button } from '@/components/ui'`.
- **Responsive rule**: components switch layout at the four token breakpoints
  only (320 / 768 / 1024 / 1440). `Table` renders a real `<table>` from `md` up
  and stacked cards below `md` so nothing forces horizontal scroll at 320px.
- **Dark mode** is driven by the `data-theme` attribute on `<html>` (set by
  `ThemeProvider`), never by `prefers-color-scheme` alone.
- **Verification**: `npm test` (Vitest + jsdom), `npm run typecheck`,
  `npm run build`. The living style guide is at the `/style-guide` route
  (`src/pages/StyleGuide.tsx`).

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
- **TaskFlow web design system** lives under
  `.level5-data/projects/proj_2d3b48e3f1cf/apps/web` (distinct from the
  `frontend/` Meridian system above). Tokens are hand-authored in
  `src/styles/tokens.css`; `tailwind.config.ts` `extend`s Tailwind so every
  utility resolves to a `var(--…)`. Guard tests:
  `src/styles/__tests__/no-magic-values.test.ts` (no colour literals in
  components), `tokens.contrast.test.ts` (WCAG 2.1 AA per theme) and
  `tokens.structure.test.ts`. Run `npm run typecheck|lint|test|build
  --workspace @taskflow/web`.
- Contrast gotcha (learned the hard way): a single `--color-primary` cannot be
  both a fill (carries white text) *and* text-on-surface in dark mode — the fill
  is only ~3.95:1 on the surface. The system therefore has a separate
  `--color-primary-text` (brand-600 light / brand-300 dark) for primary-coloured
  text (`text-primary-text`); never use `text-primary`. Likewise raw status
  fills (e.g. `text-warning` = warning-500, 2.35:1 on white) fail the 3:1
  non-text bar as glyphs — use the `*-subtle-fg` variants on surfaces.
- **TaskFlow persistence layer** lives under
  `.level5-data/projects/proj_6128c135609c/backend` (SQLAlchemy models, Alembic
  migrations `0001_init`…`0006_rls`, tenant-scoped repositories, seed script).
  It implements `docs/data-model.md` exactly. Verify with:
  `cd .../backend && DATABASE_URL=... .venv/bin/alembic upgrade head &&
  .venv/bin/python -m scripts.seed --reset && .venv/bin/python -m pytest -q`
  (61 tests). Needs a PostgreSQL instance; the suite uses `taskflow_test` and
  `taskflow_test_mig` databases. `alembic check` must report "No new upgrade
  operations detected".
- RLS gotcha: `memberships`, `tasks`, `audit_events` have `FORCE ROW LEVEL
  SECURITY`, so plain `psql`/raw queries with no `app.current_tenant` GUC see
  zero rows. Tests and the seed set the GUC via `tenant_transaction(...)`.
- The append-only guard on `audit_events` (trigger + REVOKE) blocks cascade
  deletes of tenants; the seed's `--reset` and tenant offboarding set the
  session-local `app.audit_maintenance='on'` escape.
- Alembic naming convention: pass **short** check-constraint names
  (`name="status_valid"`) in migrations/models — the `ck_%(table)s_%(name)s`
  convention adds the `ck_<table>_` prefix. Passing an already-prefixed name
  double-prefixes it.
- **CABER villa design brief** (`proj_38c100961ec0`, task `task_a5b629b2ddc4`):
  the governing room program / dimensional brief for the two-storey modern
  villa lives in that project's `docs/room_program.json` (machine-readable,
  single source of truth for areas + dimensions) and `docs/design_brief.md`
  (narrative). It is the upstream input to the BIM model, site layout,
  floor-plan set, area schedule and verification tasks in that project's task
  graph. Regenerate + verify with:
  `cd .level5-data/projects/proj_38c100961ec0 &&
   python3 scripts/build_room_program.py && python3 tests/test_room_program.py`
  (24 checks). Conventions: x=east, z=north, y=up (matches
  `level5/caber/models.py`); each storey tiles a 14×10 m footprint with no
  overlaps; `clear_dimensions` subtract a 0.2 m wall allowance for enclosed
  rooms only; `ceiling_height_m` is numeric for enclosed spaces and `null`
  (open to sky) for the terrace/pool/deck. All 13 code/planning items carry
  `status: UNVERIFIED_HYPOTHESIS` because the project ran with
  `model_prior_no_retrieval` (no jurisdiction, no sources).

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
