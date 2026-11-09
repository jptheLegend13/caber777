# LEVEL 5 — Project Roadmap

Working milestones per the master build directive. Each milestone is marked with
what is **implemented and verified** versus what remains.

Legend: `[x]` done and verified · `[~]` partially implemented · `[ ]` not started

---

## MILESTONE 1 — Working engineering platform foundation — `[x]`

- [x] Text command box (React + TypeScript workspace).
- [x] Project workspace with live panels.
- [x] FastAPI backend over the OpenHands Agent Server.
- [x] OpenHands SDK / Agent Server connection (v1.60.1, verified reachable).
- [x] Task planning (understanding → specification → task graph).
- [x] Real coding agents executing in the project workspace.
- [x] File creation and artifact recording.
- [x] Test execution by the agents, with results captured.
- [x] Completion reporting (`LEVEL5_REPORT.md`) and SSE progress.

## MILESTONE 2 — Universal agent orchestration — `[x]`

- [x] Agent registry with 38 specialist roles across 6 disciplines.
- [x] Dynamic specialist creation (`register_dynamic`).
- [x] Provider-agnostic LLM client (OpenAI-compatible gateway).
- [x] Dependency-aware task graph with parallel execution.
- [x] Persistent project state (SQLite + JSON), resumable.
- [x] Review and repair tasks in the standard plan shape.
- [x] Agent activity interface (SSE stream + activity tab).
- [x] Per-task git worktree isolation so parallel agents cannot overwrite each
  other's files (`worktrees.py`; opt-in via `LEVEL5_TASK_WORKTREES=1`;
  `tests/test_worktrees.py`; live-verified with a real agent conversation).

## MILESTONE 3 — Universal creation capability — `[~]`

Verified by planning probe (`scripts/`-equivalent: plan four distinct requests and
inspect role allocation and dependency chains):

| Request | Domain detected | Module | Tasks | Specialist roles allocated |
|---|---|---|---|---|
| Mobile fitness tracker | `mobile_app` | A | 12 | mobile, backend, ui/ux, security, devops, testing, review |
| Multi-agent research assistant | `multi_agent_system` | A | 12 | multi-agent orchestration, ai research, ML, database, backend, review |
| Linear-attention research + benchmark | `research` | B | 9 | technology research, ai research, ML, data, performance, testing |
| Multi-tenant SaaS billing | `backend_api` | A | 12 | api, backend, cloud, devops, database, security, performance, review |

- [x] Web application workflow (plan → backend → frontend → tests → review).
- [x] Backend / API / database workflows.
- [x] AI application and multi-agent workflows, with the right specialists.
- [x] Mobile workflow planning (mobile_engineer, offline sync, native
  integrations, secure credential storage).
- [x] Cloud / DevOps workflow planning (cloud_engineer, devops_engineer,
  observability, CI/CD, idempotent webhooks).
- [~] Execution (not just planning) has been demonstrated end-to-end for the web
  application domain. The other domains are planned correctly and routed to the
  right agents, but a full execution run has not been recorded for each.
- [x] Browser preview for web applications: the app's real build is run, its
  output is served at `/preview/`, and the frontend preview tab shows the build
  command, status and output. A failing build is repaired (bounded) and
  re-built, not hidden. Verified against a real generated monorepo: the build
  runs and its true result is reported (it failed — see `RUNS.md`).
- [ ] Verified preview/emulator integration for mobile and desktop.

## MILESTONE 4 — Problem-Solving Intelligence — `[~]`

- [x] Research with real retrieval (Tavily / Brave / DuckDuckGo) and cited,
  classified findings.
- [x] Computational model generation, execution and one informed repair attempt.
- [x] Independent verification of results with stated limitations and confidence.
- [~] Structured scientific workflow beyond the computational-model path
  (constraint solving, alternative-solution search) is not yet a separate module.

## MILESTONE 5 — Building Creation Intelligence — `[x]`

- [x] Three-block architectural specification interface (blocks 1–3).
- [x] Procedural construction: floors, walls with openings, stairs, roof,
  outdoor areas, objects, materials, lighting.
- [x] Interiors and exteriors from the specification.
- [x] Objects with position, rotation, scale, behaviours and interactions.
- [x] Interactive 3D viewport (Three.js) with object selection and inspection.
- [x] Natural-language editing routed to the building's agent conversation.
- [x] Independent validation (11 checks) with a published score.

## MILESTONE 6 — Integrated CABER — `[x]`

- [x] One command interface and one project store for all three intelligences.
- [x] Shared research, agent execution, file management and version history.
- [x] Per-project module tagging (A / B / C / P).
- [x] A single run that spans two intelligences: an application request that
  displays a building is served by Intelligence A consuming the real scene
  artifact produced by Intelligence C (`integration.py`,
  `POST /api/projects/{id}/building-viewer`, and command-box auto-detect in
  `_run_full_pipeline`). Verified live: the command box built a building
  (275 primitives) and then a viewer application that renders that exact scene,
  served at `/preview/`; covered by `tests/test_integration.py`.

## MILESTONE 7 — Continuous research and improvement — `[~]`

- [x] Reproducible self-benchmarking: every run records real measured metrics
  (task success rate, test pass rate, acceptance-criteria rate, artifacts,
  conversations, elapsed time, model) to the benchmark store.
- [x] Controlled self-improvement loop: detect (from real records) → propose →
  screen → record. Proposals are never auto-applied, and a screen rejects any
  proposal that weakens a safety control, widens permissions, removes an
  approval gate, applies self-modification to production, exposes credentials
  or creates agents recursively. Each proposal must name its tests and its
  before/after comparison.
- [x] Independent review and accept/reject decision by a separate reviewer agent:
  `SelfImprovementEngine.review` is a distinct, adversarial agent call that may
  only ever reject a proposal the deterministic screen already rejected, and it
  never accepts a proposal with no tests or comparison plan. Acceptance
  authorises isolated implementation behind its tests, never deployment.
  Verified live: the reviewer rejected a plausible-sounding retry proposal
  because its comparison plan was statistically meaningless and its idempotency
  risk was unexamined.
- [x] Innovation-to-prototype engine (§13): a novel idea is investigated (prior
  art via real retrieval, technical gap, feasibility, alternatives), a
  falsifiable hypothesis is formed, a prototype is generated and *actually
  executed* by the shared sandboxed runner, and the run is evaluated with honest
  confidence and limitations. Reachable from the command box, which routes
  novel-idea requests to it (see `tests/test_routing.py`).
- [~] The competitive benchmark suite: a fixed, versioned set of equivalent
  engineering tasks with objective criteria, a deterministic scorer, per-system
  aggregation and REST endpoints now exist (`benchmark_suite.py`,
  `/api/benchmarks/suite*`; `tests/test_benchmark_suite.py`). Missing runs are
  recorded as `not_run`, never as a fabricated score, and a system with no
  scored task reports a null success rate. **No external system has been run
  against the suite**: this environment cannot drive Claude Code, Codex, Cursor,
  Devin, Factory or Antigravity under equivalent conditions. **No superiority
  claim is made.** A real comparison remains the outstanding prerequisite.

---

## Known limitations (stated honestly)

1. **No competitive benchmark has been run.** No claim of superiority over any
   other system is made anywhere in this platform. The directive forbids it
   without equivalent-condition evidence.
2. **CABER geometry is box-based** and rendered with Three.js. It is a real
   interactive viewport, not a match for Unreal Engine, Blender or Houdini.
3. **Physical production is out of scope.** CABER designs and simulates
   architecture; it does not manufacture, and it does not claim structural
   engineering certification.
4. **Research is only as good as retrieval.** With no search provider
   configured, the engine labels all findings as unverified hypotheses.
5. **Agent reliability is bounded by the model.** A task can fail; failures are
   recorded verbatim and dependent tasks are skipped rather than faked.
