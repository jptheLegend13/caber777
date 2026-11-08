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

## MILESTONE 3 — Universal creation capability — `[~]`

- [x] Web application workflow (plan → backend → frontend → tests → review).
- [x] Backend / API / database workflows.
- [x] AI application and agent workflows (roles registered and routed).
- [~] Mobile, desktop, enterprise, cloud and DevOps workflows: roles exist and
  the planner routes to them, but no dedicated end-to-end acceptance run has
  been recorded for each.
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

## MILESTONE 6 — Integrated CABER — `[~]`

- [x] One command interface and one project store for all three intelligences.
- [x] Shared research, agent execution, file management and version history.
- [x] Per-project module tagging (A / B / C / P).
- [ ] A single run that spans two intelligences (for example, an application that
  renders a CABER building) is not yet implemented.

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
- [ ] Independent review and accept/reject decision by a separate reviewer agent
  (the review step currently requires a human decision).
- [ ] The competitive benchmark suite: a fixed set of equivalent tasks run
  against comparable systems under the same model and hardware. **Not run.**
  No superiority claim is made anywhere in this platform.

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
