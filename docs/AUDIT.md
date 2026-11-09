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

### F5 — Event stream paging could duplicate or skip events (severity: medium) — **FIXED this cycle**

`AgentServerClient.get_all_events` paged on the last event's `timestamp`
(`timestamp__gte`). Events that share a timestamp — the norm inside a single
agent step — are then either repeated across a page boundary or skipped when a
whole page falls inside one timestamp. The server actually returns an opaque
`next_page_id` cursor; the client now follows it and treats it as
authoritative. Covered by `tests/test_event_pagination.py`.

### F6 — Gateway degradation was invisible (severity: medium) — **FIXED this cycle**

`GET /api/health` reported `status: ok` even when the bare-LLM gateway was
dead, because nothing probed it. Fix: `LLMClient.probe_gateway()` checks the
model registry and `/api/health` now reports `llm.transport`,
`llm.gateway_models_available` and `llm.ready`, and returns `degraded` when an
explicit `gateway` transport cannot serve models. `auto` stays `ok` because it
falls back to `ask_agent`.

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
| Frontend workspace UI (tabs, SSE) | IV | `npm run build` passes; served at `/` |
| Voice input | IU | `useVoiceInput.ts`; needs a real browser session (no mic in CI) |
| File/image upload | IV (new) | `POST /attachments`; see F4 |
| Browser preview of a built web app | IV | `/preview/status`, `/preview/*`; traversal rejected (400) |
| Build → repair → rebuild | IV | `tests/test_build_repair.py`; live build passed |
| Model/provider registry | IV | `tests/test_providers.py`; `/api/providers` |
| Bare model calls | IV (new) | was MI/BL (F1) |
| Self-improvement loop (screened proposals) | IV | `tests/test_self_improvement.py` |
| Self-benchmarking (own metrics) | IV | `tests/test_benchmarks.py` |
| **Competitive benchmark suite** | **MI** | Not run; no superiority claim is made |
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
| Constraint solving / alternative search | MI | not a separate module |
| **Innovation-to-prototype engine (§9)** | **MI** | no dedicated engine; the research path partially covers it |

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

`backend/.venv/bin/python -m pytest -q` → **138 passed** (before this cycle's
additions). The suite replaces only the network boundary in orchestrator tests
and states that in the module.

## 5. Honest limitations carried forward

1. No competitive benchmark has been run; no superiority claim is made.
2. CABER geometry is box-based and Three.js-rendered — a real viewport, not a
   match for Unreal/Blender/Houdini.
3. Physical manufacture and structural certification are out of scope.
4. Research is only as good as retrieval; with no provider key, findings are
   labelled unverified.
5. Agent reliability is bounded by the model; failures are recorded, not hidden.
6. Mobile/desktop previews and non-web full executions are not yet recorded.
