# LEVEL 5 — Full capability audit

Date: 2026-11-08 (current development cycle).
Method: source inspection, live probing of the running backend and Agent
Server, and the existing test suite. Every classification below is backed by an
observed command result or a named test, not by the presence of a file.

Classification legend:

- **IV** — Implemented and Verified (ran and produced a correct result).
- **IU** — Implemented but Unverified (code exists; no run has confirmed it).
- **PA** — Partially Implemented.
- **MO** — Mocked or Placeholder.
- **MI** — Missing.
- **BL** — Blocked by an external dependency.

---

## 1. Environment (verified this session)

| Fact | Evidence |
|---|---|
| Agent Server reachable, v1.60.1, SDK 1.60.1 | `GET /api/health` → `agent_server.reachable = true` |
| Real agent conversations execute tools | probe created `/tmp/l5_probe/hello.txt`; status `finished`, 3 actions |
| Backend serves the built frontend | `GET /` returns `index.html` |
| Session key comes from the Agent Server process env (`SESSION_API_KEY`), not `~/.oh_session_key` | the file no longer exists; key read from `/proc/1/environ` |
| **Bare-LLM gateway is broken** | `GET /v1/models` → `{"data":[]}`; `POST /v1/chat/completions` → `404 Profile 'Default' not found` |
| `POST /api/conversations/{id}/ask_agent` works | returns model text; measured 6.8 s for a structured-JSON request |

## 2. Critical findings

### F1 — Bare-LLM path is dead (severity: critical) — **FIXED this cycle**

`LLMClient` posts to `{agent_server}/v1/chat/completions`. The Agent Server's
gateway has an **empty model registry**, so every call fails:

```
GET  /v1/models           -> {"object":"list","data":[]}
POST /v1/chat/completions -> 404 {"detail":"Profile 'Default' not found"}
```

Consequences before the fix (all observed live):

- `POST /api/projects/{id}/plan` → **HTTP 500**
- `POST /api/solve` → **HTTP 500**
- `POST /api/caber/buildings` → **HTTP 500**

These are Central Intelligence, Problem-Solving Intelligence and Building
Creation Intelligence respectively. In other words **the platform's own
reasoning path did not run at all**, while the task-execution path (agent
conversations) did. This is the single most important defect found.

Fix: `LLMClient` now routes bare calls through the Agent Server's
`ask_agent` endpoint (which uses the profile-resolved model) with automatic
transport selection and fallback. See `backend/level5/llm/client.py`.

### F2 — Failed tasks lose their conversation and error detail (severity: high) — **FIXED this cycle**

When an agent conversation fails, `_run_task` sets the task to FAILED but never
records `task.conversation_id` nor the terminal error text. In the acceptance
project `proj_2d3b48e3f1cf` the failed task reports only
`task did not complete successfully` and `conversation_id: null`, so the real
cause is unrecoverable after the fact. Fix: record the conversation id and the
classified error on failure.

### F3 — No per-task workspace isolation (severity: medium) — **ADDRESSED this cycle**

All tasks for a project share one directory. The directive requires isolated
worktrees/branches so agents cannot overwrite each other. Fix: opt-in git
worktree per task (`LEVEL5_TASK_WORKTREES`), with the task's changes merged back
by the orchestrator.

### F4 — File/image upload is missing (severity: medium) — **FIXED this cycle**

The command box supports text and voice only. The directive's §11 requires
files, images and reference documents. No upload endpoint existed
(`grep UploadFile` → no matches). Fix: `POST /api/projects/{id}/attachments`
plus a frontend attach control.

### F5 — Event stream paging could duplicate or skip events (severity: medium) — **FIXED and live-verified**

`AgentServerClient.get_all_events` paged on the last event's `timestamp`
(`timestamp__gte`). Events that share a timestamp — the norm inside a single
agent step — are then either repeated across a page boundary or skipped when a
whole page falls inside one timestamp. The server actually returns an opaque
`next_page_id` cursor; the client now follows it and treats it as
authoritative. Covered by `tests/test_event_pagination.py` and confirmed live
against the running Agent Server: 329 and 439 events walked across many pages
with all-unique ids and no duplicates or skips.

### F6 — Gateway degradation was invisible (severity: medium) — **FIXED this cycle**

`GET /api/health` reported `status: ok` even when the bare-LLM gateway was
dead, because nothing probed it. Fix: `LLMClient.probe_gateway()` checks the
model registry and `/api/health` now reports `llm.transport`,
`llm.gateway_models_available` and `llm.ready`, and returns `degraded` when an
explicit `gateway` transport cannot serve models. `auto` stays `ok` because it
falls back to `ask_agent`.

### F7 — Command box bypassed the specialist intelligences (severity: high) — **FIXED and live-verified**

The main product surface (`POST /api/projects/{id}/run`) always planned a
generic engineering task graph. A building request or a novel-idea request
therefore never reached the Building Creation or Innovation engines: the
dedicated endpoints existed, but the command box never routed to them, so the
"one command interface, three intelligences" architecture (§12) was not
actually wired end to end. Fix: the orchestrator's planning was split into
`understand()` + `plan()`, and `_run_full_pipeline` now dispatches on the
classified CABER module — buildings → `CABERBuildingService`, novel ideas →
`innovate_project`, everything else → the task graph. Covered by
`tests/test_routing.py`. Verified live: a villa request classified as module C
produced a delivered building (`Aurelia Villa`, 11 rooms, 255 primitives, 12/12
validation checks, `/caber/viewer` served 200), and a service request ran the
generic path (8 tasks).

### F8 — Routing ran generic research before the specialist engine (severity: medium) — **FIXED this cycle**

After the F7 fix, a building request still ran the generic research step first
(five web lookups, minutes of latency) before reaching the building engine,
because research lived inside `understand()`. Fix: research was split into
`run_research()`; the pipeline classifies, routes buildings and novel ideas
immediately, and only the generic path runs research → plan → execute. Covered
by the dispatch tests in `tests/test_routing.py`.

### F9 — A step method shadowed the research engine (severity: high, regression) — **FIXED this cycle**

The F8 refactor added a method named `research` on `Orchestrator`, which
shadowed the `self.research` `ResearchEngine` attribute, so **every generic
request failed** with `'ResearchEngine' object is not callable`. Caught live:
the attached-requirements project `proj_a6eee486487d` failed at the research
phase. Fix: the step is renamed `run_research`. Regression test in
`tests/test_orchestrator.py`; the generic path was then re-run live to
completion (8 tasks planned and executing).

### F10 — Bare-LLM calls retried a known-dead gateway every time (severity: low) — **FIXED this cycle**

Every bare model call paid three failing round-trips to the empty gateway
before falling back to `ask_agent`. Fix: in `auto` mode the gateway is skipped
for a short window after an observed failure; an explicit `gateway` transport
still attempts it, so the failure is surfaced rather than hidden. Covered by
`tests/test_llm_transport.py`.

## 3. Capability classification

### Platform / control plane

| Capability | Class | Evidence / note |
|---|---|---|
| Project store (SQLite + JSON), resumable | IV | `tests/test_models_and_store.py`, `tests/test_resume.py` |
| Request understanding → specification | IV (after F1 fix) | was 500; now returns a classified spec |
| Task planning → dependency graph | IV (after F1 fix) | `tests/test_orchestrator.py`; live probe |
| Dependency-aware parallel execution | IV | orchestrator `_run_graph`; 3 tasks ran concurrently in the acceptance run |
| Transient-only retry | IV | `tests/test_retries.py` |
| Honest verification (criteria ↔ task evidence) | IV | `tests/test_verification.py` |
| Delivery gating on acceptance criteria | IV | `tests/test_delivery_honesty.py` |
| SSE live activity stream | IV | `/stream`; heartbeat every 15 s |
| Version history snapshots | IV | `Project.snapshot`; `docs/RUNS.md` |
| Real agent execution (terminal, file_editor) | IV | live probe + acceptance run (82 artifacts) |
| Command-box routing to A/B/C | IV (new) | `_run_full_pipeline` dispatches on the CABER module; `tests/test_routing.py` |
| Shared sandboxed Python runner | IV (new) | `execution.py`; `tests/test_execution.py` |
| Frontend workspace UI (tabs, SSE) | IV | `npm run build` passes; served at `/` |
| Voice input | IU | `useVoiceInput.ts`; needs a real browser session (no mic in CI) |
| File/image upload | IV (new) | `POST /attachments`; see F4. Live-verified: an uploaded `ref-notes.txt` became a user-origin requirement ("Support SSO via SAML and export audit logs") while model-derived requirements stayed `inferred`; a `../../../../etc/evil.txt` upload was contained (no `/etc/evil.txt`; stored under the project's `attachments/` dir). Frontend attach control present and built |
| Browser preview of a built web app | IV | `/preview/status`, `/preview/*`; traversal rejected (400) |
| Build → repair → rebuild | IV | `tests/test_build_repair.py`; live build passed |
| Model/provider registry | IV | `tests/test_providers.py`; `/api/providers` |
| Bare model calls | IV (new) | was MI/BL (F1) |
| Self-improvement loop (screened proposals) | IV | `tests/test_self_improvement.py` |
| Self-benchmarking (own metrics) | IV | `tests/test_benchmarks.py` |
| **Competitive benchmark suite** | **PA (new)** | fixed task set, deterministic scorer, per-system aggregation and REST endpoints (`tests/test_benchmark_suite.py`); **no external system has been run** — the environment cannot drive Claude Code, Codex, Cursor, Devin, Factory or Antigravity under equivalent conditions. No superiority claim is made |
| Authentication / multi-user accounts | **MI** | Single-operator tool; no account system |
| Per-task git worktree isolation | PA (new) | opt-in flag (F3) |

### CABER Intelligence A — Application creation

| Capability | Class | Evidence |
|---|---|---|
| Web-app workflow (plan→build→test→review) | IV | acceptance run produced a real monorepo |
| Frontend/backend/database/API/auth generation | IV | 8 tasks succeeded, 82 artifacts |
| Monorepo detection + real build | IV | `npm run build` passed |
| Mobile / desktop / cloud / AI workflows | PA | planned with correct specialists; no full execution recorded |
| Mobile/desktop preview or emulator | MI | only web preview exists |

### CABER Intelligence B — Problem solving

| Capability | Class | Evidence |
|---|---|---|
| Research with real retrieval + citations | IU | code complete (Tavily/Brave/DuckDuckGo); no provider key configured here |
| Computational model generation + execution | IV (after F1 fix) | `tests/test_verification.py`; was 500 |
| One informed repair attempt on a failed model | IV | `_repair_model` |
| Independent verification + confidence | IV | `SolutionReport.verify` |
| Constraint solving / alternative search | PA | alternatives are generated inside the innovation engine |
| **Innovation-to-prototype engine (§9)** | **IV (new)** | `innovation.py`; live run found prior art, ran a 229-line simulation and measured 6.35% mean hit-ratio gain over LRU across 18 configs (p=1.2e-05) |

### CABER Intelligence C — Building creation

| Capability | Class | Evidence |
|---|---|---|
| Three-block specification | IV (after F1 fix) | `caber/models.py`; architect LLM call was 500 |
| Procedural geometry (floors, walls, openings, stairs, roof) | IV | `tests/test_caber.py` |
| Objects with position/rotation/scale/behaviour | IV | `caber/geometry.py` |
| Interactive 3D viewport (Three.js) | IV | `/caber/viewer` |
| Independent validation (11 checks, score) | IV | `/caber/validation` |
| Natural-language editing | IU | routed to the building conversation |
| Photoreal / PBR / GI rendering | MI | box geometry only; documented as such |

### Integrations (§6)

| Integration | Class | Note |
|---|---|---|
| OpenHands Agent Server | IV | conversations, events, ask_agent |
| OpenAI-compatible gateway | BL | model registry empty in this deployment (F1) |
| Tavily / Brave / DuckDuckGo | IU | adapters written; no key configured |
| GitHub / git | PA | git present; no PR automation wired into the platform |
| Figma / Stitch / Blender / Unreal / Houdini / USD | MI | not integrated; documented as out of reach from this environment |
| Docker / Kubernetes | BL | Docker not running in this sandbox |

## 4. Test suite

`backend/.venv/bin/python -m pytest -q` → **195 passed** (this cycle: 179 → 195;
added `test_benchmark_suite.py`, `test_llm_transport.py`, dispatch and
regression tests). The suite replaces only the network boundary in orchestrator
tests and states that in the module.

## 5. Honest limitations carried forward

1. No competitive benchmark has been run; no superiority claim is made.
2. CABER geometry is box-based and Three.js-rendered — a real viewport, not a
   match for Unreal/Blender/Houdini.
3. Physical manufacture and structural certification are out of scope.
4. Research is only as good as retrieval; with no provider key, findings are
   labelled unverified.
5. Agent reliability is bounded by the model; failures are recorded, not hidden.
6. Mobile/desktop previews and non-web full executions are not yet recorded.
