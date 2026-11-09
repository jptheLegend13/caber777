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
