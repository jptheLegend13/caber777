# Generated deliverables — design and persistence notes

These notes were captured while LEVEL 5 generated and iterated on real
deliverable projects. The deliverables themselves live under
`backend/.level5-data/projects/<id>/`, which is **gitignored** (it is 1.8 GB of
generated output and contains `node_modules`). Nothing here is part of the
LEVEL 5 platform source; it is recorded so the knowledge is not lost when a
data directory is cleaned.

They are kept out of `AGENTS.md` on purpose: `AGENTS.md` describes the
repository, and these paths are not in the repository.

---

## Enterprise Task Manager (web_app) — persistence layer

The Enterprise Task Manager deliverable lives under
`.level5-data/projects/proj_bd6079fa3ead/`. Persistence lives in its `backend/`:

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
- `alembic/versions/0001..0004` — initial schema, tasks/assignments,
  audit/tokens, guarded admin seed. `scripts/migrate.sh` wraps
  `alembic upgrade head`.
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

The deliverable frontend implements a bespoke **Meridian** design system. There
is no stock Tailwind theme: `tailwind.config.ts` *replaces* (not `extend`s)
`colors`, `fontFamily`, `fontSize`, `spacing`, `borderRadius`, `boxShadow`,
`zIndex` and `screens` with values read directly from the generated token
module. A class not backed by a Meridian token simply does not exist.

- Token source of truth is `docs/tokens.json`; `scripts/gen_tokens.py` emits
  `frontend/src/design/tokens.{css,ts}`. Do not hand-edit the generated files —
  re-run the generator. `src/design/__tests__/theme.test.ts` asserts the
  generated module still deep-equals `docs/tokens.json`.
- Theme layer: `frontend/src/styles/tokens.css` holds shorthand aliases and the
  `[data-theme='dark']` remap of *semantic* tokens only; `global.css` holds
  base/reset, the `md-visually-hidden` and other utilities, and the
  `prefers-reduced-motion` kill-switch.
- Import order matters in `src/main.tsx`: `design/tokens.css` →
  `styles/tokens.css` → `styles/global.css`.
- Component library: `frontend/src/components/ui/` (Button, Input, Select,
  Textarea, Checkbox, Card/Panel, Badge/StatusBadge/PriorityBadge,
  Modal/ConfirmDialog, Table, Toast, Avatar, Tabs, EmptyState, Tooltip, Skeleton,
  Spinner, Icon, ThemeProvider) plus layout primitives in `ui/layout/`
  (Box, Container, Stack/Cluster/Spacer, Grid, Divider, PageHeader). Import from
  the barrel: `import { Button } from '@/components/ui'`.
- Responsive rule: components switch layout at the four token breakpoints only
  (320 / 768 / 1024 / 1440). `Table` renders a real `<table>` from `md` up and
  stacked cards below `md` so nothing forces horizontal scroll at 320px.
- Dark mode is driven by the `data-theme` attribute on `<html>` (set by
  `ThemeProvider`), never by `prefers-color-scheme` alone.
- Verification: `npm test` (Vitest + jsdom), `npm run typecheck`,
  `npm run build`. The living style guide is at the `/style-guide` route
  (`src/pages/StyleGuide.tsx`).

## TaskFlow — web design system

Lives under `.level5-data/projects/proj_2d3b48e3f1cf/apps/web`. Tokens are
hand-authored in `src/styles/tokens.css`; `tailwind.config.ts` `extend`s
Tailwind so every utility resolves to a `var(--…)`. Guard tests:
`src/styles/__tests__/no-magic-values.test.ts` (no colour literals in
components), `tokens.contrast.test.ts` (WCAG 2.1 AA per theme) and
`tokens.structure.test.ts`. Run
`npm run typecheck|lint|test|build --workspace @taskflow/web`.

Contrast gotcha: a single `--color-primary` cannot be both a fill (carries white
text) *and* text-on-surface in dark mode — the fill is only ~3.95:1 on the
surface. The system therefore has a separate `--color-primary-text`
(brand-600 light / brand-300 dark) for primary-coloured text
(`text-primary-text`); never use `text-primary`. Likewise raw status fills
(e.g. `text-warning` = warning-500, 2.35:1 on white) fail the 3:1 non-text bar as
glyphs — use the `*-subtle-fg` variants on surfaces.

## TaskFlow — persistence layer

Lives under `.level5-data/projects/proj_6128c135609c/backend` (SQLAlchemy
models, Alembic migrations `0001_init`…`0006_rls`, tenant-scoped repositories,
seed script). It implements `docs/data-model.md` exactly. Verify with:

```bash
cd .../backend && DATABASE_URL=... .venv/bin/alembic upgrade head && \
  .venv/bin/python -m scripts.seed --reset && .venv/bin/python -m pytest -q
```

(61 tests). Needs a PostgreSQL instance; the suite uses `taskflow_test` and
`taskflow_test_mig` databases. `alembic check` must report "No new upgrade
operations detected".

- RLS gotcha: `memberships`, `tasks`, `audit_events` have
  `FORCE ROW LEVEL SECURITY`, so plain `psql`/raw queries with no
  `app.current_tenant` GUC see zero rows. Tests and the seed set the GUC via
  `tenant_transaction(...)`.
- The append-only guard on `audit_events` (trigger + REVOKE) blocks cascade
  deletes of tenants; the seed's `--reset` and tenant offboarding set the
  session-local `app.audit_maintenance='on'` escape.
- Alembic naming convention: pass **short** check-constraint names
  (`name="status_valid"`) in migrations/models — the `ck_%(table)s_%(name)s`
  convention adds the `ck_<table>_` prefix. Passing an already-prefixed name
  double-prefixes it.

## CABER villa design brief

`proj_38c100961ec0`, task `task_a5b629b2ddc4`. The governing room program /
dimensional brief for the two-storey modern villa lives in that project's
`docs/room_program.json` (machine-readable, single source of truth for areas +
dimensions) and `docs/design_brief.md` (narrative). It is the upstream input to
the BIM model, site layout, floor-plan set, area schedule and verification tasks
in that project's task graph. Regenerate + verify with:

```bash
cd .level5-data/projects/proj_38c100961ec0 && \
  python3 scripts/build_room_program.py && python3 tests/test_room_program.py
```

(24 checks). Conventions: x=east, z=north, y=up (matches
`level5/caber/models.py`); each storey tiles a 14×10 m footprint with no
overlaps; `clear_dimensions` subtract a 0.2 m wall allowance for enclosed rooms
only; `ceiling_height_m` is numeric for enclosed spaces and `null` (open to sky)
for the terrace/pool/deck. All 13 code/planning items carry
`status: UNVERIFIED_HYPOTHESIS` because the project ran with
`model_prior_no_retrieval` (no jurisdiction, no sources).
