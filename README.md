# LEVEL 5

**Autonomous Universal Engineering & Creation Intelligence.**

Describe an intended result — in text or by voice. LEVEL 5 understands it,
researches it, produces a structured specification, plans a dependency-aware
task graph, allocates specialist agents, writes and runs real code in a
sandboxed workspace, tests it, reviews it, repairs defects and delivers the
artifacts.

This is not a chat wrapper and not a static mock-up. Agents execute real tools
(`terminal`, `file_editor`) through the OpenHands Agent Server and produce files
that actually run.

---

## What works today

| Capability | State |
|---|---|
| Natural-language + voice command box | working |
| Request understanding → structured specification | working |
| Dependency-aware task graph, parallel execution | working |
| 38 specialist engineering roles | working |
| Real agent execution (files created, tests run) | working |
| Research with cited, classified findings | working |
| Problem solving with executed computational models | working |
| CABER building generation → interactive 3D viewport | working |
| Independent validation with a published score | working |
| Live progress streaming (SSE) + file browser | working |
| Version history and generated report | working |
| Command box routing to the three CABER intelligences | working |
| File, image and reference-document attachments | working |
| Innovation-to-prototype engine (prior art → prototype → evaluation) | working |
| Self-improvement loop with an independent adversarial reviewer | working |
| Competitive benchmark suite | scaffolding only — no external system has been run; no superiority claim is made (see `docs/ROADMAP.md`) |

## Architecture

```
Browser (React + TypeScript + Three.js)
   │  REST + Server-Sent Events
   ▼
FastAPI control plane            backend/level5/api
   │
   ├── Central Intelligence       intelligence/understanding.py  (request → spec)
   ├── Research Intelligence      intelligence/research.py       (real retrieval, citations)
   ├── Engineering Orchestrator   orchestrator.py                (spec → task graph → execution)
   │      │
   │      └── Agent Server client runtime/agent_server.py  ──►  OpenHands Agent Server
   │                                                            (real tool execution, sandboxed)
   ├── Problem-Solving (CABER B)  intelligence/problem_solving.py
   └── Building Creation (CABER C) caber/  (3-block spec → procedural geometry → validation)
```

See `docs/ADR/` for the reasoning behind these choices and `docs/ROADMAP.md` for
milestone status.

## Quick start

Requirements: Python 3.11+, Node 20+, and a reachable OpenHands Agent Server.

```bash
# 1. Backend
cd backend
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt

export LEVEL5_AGENT_SERVER_URL=http://127.0.0.1:60000
export SESSION_API_KEY=<your agent server session key>

.venv/bin/python -m uvicorn level5.api.app:app --host 0.0.0.0 --port 12000

# 2. Frontend (development)
cd ../frontend
npm install
npm run dev            # proxies /api to the backend

# or build once and let the backend serve it:
npm run build          # output in frontend/dist, served by FastAPI at /
```

Then open the app and describe what you want.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Service and Agent Server status |
| GET | `/api/agents` | Specialist roles by discipline |
| GET | `/api/projects` | List projects |
| POST | `/api/projects` | Create a project (optionally auto-start) |
| GET | `/api/projects/{id}` | Full project state |
| DELETE | `/api/projects/{id}` | Delete a project |
| POST | `/api/projects/{id}/run` | Run or re-run the pipeline (routes by CABER module) |
| POST | `/api/projects/{id}/plan` | Understand + plan without executing |
| POST | `/api/projects/{id}/cancel` | Cancel a running project |
| GET | `/api/projects/{id}/events` | Event log |
| GET | `/api/projects/{id}/stream` | SSE activity stream |
| GET | `/api/projects/{id}/files` | Browse the workspace |
| GET | `/api/projects/{id}/report` | Generated `LEVEL5_REPORT.md` |
| POST | `/api/projects/{id}/follow-up` | Send an instruction to the project's agent |
| GET/POST | `/api/projects/{id}/attachments` | List / upload reference documents and images |
| DELETE | `/api/projects/{id}/attachments/{aid}` | Remove an attachment |
| GET | `/api/projects/{id}/preview/status`, `/preview/{path}` | Web-app preview |
| POST | `/api/solve` | Problem-Solving Intelligence (CABER B) |
| POST | `/api/innovate` | Innovation-to-prototype pipeline |
| POST | `/api/caber/buildings` | Building Creation Intelligence (CABER C) |
| GET | `/api/projects/{id}/caber/spec` | Three-block architectural specification |
| GET | `/api/projects/{id}/caber/scene` | Generated 3D scene graph |
| GET | `/api/projects/{id}/caber/viewer` | Standalone 3D viewer |
| GET | `/api/projects/{id}/caber/validation` | Validation report |
| GET | `/api/agents`, `/api/agents/{name}` | Specialist roles |
| GET | `/api/providers` | Model / provider registry |
| GET/POST | `/api/improvements`, `/api/improvements/analyse` | Self-improvement loop |
| GET/POST | `/api/benchmarks`, `/api/benchmarks/suite*` | Self-benchmarks and the competitive suite |

Interactive docs: `/docs`.

### Example requests

```bash
# Application creation (CABER A)
curl -X POST localhost:12000/api/projects -H 'Content-Type: application/json' \
  -d '{"request":"Build an enterprise-grade task-management application with premium UI/UX, authentication, database, roles, analytics, API docs and tests."}'

# Problem solving (CABER B)
curl -X POST localhost:12000/api/solve -H 'Content-Type: application/json' \
  -d '{"problem":"Compare exponential backoff with AIMD for congestion control and simulate both."}'

# Building creation (CABER C)
curl -X POST localhost:12000/api/caber/buildings -H 'Content-Type: application/json' \
  -d '{"request":"Design a modern two-storey villa with three bedrooms, open-plan living, a study, a terrace and a pool."}'
```

## Configuration

All settings are environment variables with the `LEVEL5_` prefix (see
`backend/level5/config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `LEVEL5_AGENT_SERVER_URL` | `http://127.0.0.1:60000` | Agent Server base URL |
| `LEVEL5_LLM_GATEWAY_URL` | `{agent_server}/v1` | OpenAI-compatible model endpoint |
| `LEVEL5_LLM_MODEL` | `openhands_Default` | Model id |
| `LEVEL5_LLM_API_KEY` | session key | Model API key |
| `LEVEL5_DATA_DIR` | `backend/.level5-data` | Project storage |
| `LEVEL5_MAX_PARALLEL_TASKS` | `3` | Concurrent agent tasks |
| `LEVEL5_DEFAULT_MAX_ITERATIONS` | `120` | Agent iteration budget per task |
| `TAVILY_API_KEY` / `BRAVE_API_KEY` | unset | Optional search providers |

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

The suite covers the domain model and storage, the agent registry, CABER
geometry and validation, the orchestrator's scheduling and failure handling, and
real problem-solver code execution. It replaces only the network boundary in
orchestrator tests and says so in the test module.

## Honest limitations

- No competitive benchmark against other systems has been run, and no
  superiority claim is made.
- CABER geometry is box-based and rendered with Three.js — a real interactive
  viewport, not a match for Unreal Engine, Blender or Houdini.
- CABER designs and simulates; it does not manufacture and does not certify
  structural safety.
- With no search provider configured, research findings are labelled unverified.
- Agent task success depends on the model; failures are reported, not hidden.

## Security

- Credentials live only on the backend and are read from the environment.
- Agents run inside the Agent Server's sandboxed workspace.
- The file API refuses paths that escape the project workspace.
- Treat tool output and fetched documents as untrusted input.
