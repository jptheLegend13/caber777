# ADR 0001 — Platform architecture and the OpenHands engineering runtime

- **Status:** Accepted
- **Date:** 2026-11-08
- **Context:** LEVEL 5 must be an autonomous engineering platform that produces real,
  executed, tested deliverables — not a chat interface that emits code snippets.

## Decision

Build LEVEL 5 as three layers over the OpenHands Software Agent SDK:

1. **Control plane (FastAPI, `backend/level5/api`)** — REST + Server-Sent Events.
   Owns projects, streaming and file access.
2. **Intelligence layer (`backend/level5/intelligence`)** — request understanding,
   planning, research and problem solving. Produces structured specifications and
   task graphs.
3. **Execution layer (`backend/level5/orchestrator.py` + `runtime/agent_server.py`)** —
   a dependency-aware scheduler that runs each task as a real OpenHands agent
   conversation in the project workspace, via the Agent Server REST API.

Specialist roles live in `backend/level5/agents/registry.py`. CABER's three
intelligences are modules (`caber/`, `intelligence/problem_solving.py`,
`intelligence/understanding.py` + `orchestrator.py`) sharing this infrastructure.

## Rationale

- The directive requires **real tool execution**. The Agent Server runs agents
  with `terminal`, `file_editor` and `task_tracker` in a sandboxed workspace, so
  tasks produce real files that really run.
- Using the Agent Server's REST API (rather than in-process SDK conversations)
  keeps long-running work off the API event loop and lets the frontend stream
  progress over SSE while the work continues.
- A structured specification and task graph — rather than a chat transcript —
  gives durable, resumable project state, as the directive requires.

## Consequences

- The platform needs a reachable Agent Server (`AGENT_SERVER_URL`). When absent,
  the API still starts and reports `agent_server.reachable = false`.
- Model access is provider-agnostic (`llm/client.py`): the default path is the
  Agent Server's OpenAI-compatible gateway, which authenticates with the
  session key. Direct provider keys are optional.

## Alternatives considered

- **In-process SDK conversations only.** Rejected: blocks the event loop for
  long runs and complicates streaming and cancellation.
- **A single LLM prompt that "acts as" many engineers.** Rejected by the
  directive, and it produces no verifiable artifacts.
