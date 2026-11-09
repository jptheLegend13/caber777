# LEVEL 5 — intelligence independence

This document is the record of the permanent intelligence-independence
requirement: LEVEL 5 must not depend on any one company's AI API to run its
core intelligence. It states the architecture, the module inventory, the
implementation plan and the staged roadmap toward LEVEL 5's own model.

**Status of the headline claim:** LEVEL 5 does **not** have its own foundation
model. No model has been trained. This document does not claim otherwise. What
exists is an independence *architecture* plus a verified ability to run core
intelligence with no external provider.

---

## 1. Development AI vs product intelligence

The model configured in OpenHands is a development tool. It is now modelled
explicitly as a `development`-class backend (`openhands_dev_gateway`), separate
from the `internal`-class production target. The development gateway is:

- on by default only so the platform runs in this development environment;
- disabled with `LEVEL5_ALLOW_DEV_GATEWAY=0`, which drops the Agent Server
  transports entirely;
- never used as a fallback for an internal inference failure.

## 2. Architecture

```
                         ┌───────────────────────────────────────────┐
   request ──▶ Understanding ──▶ Planning ──▶ Orchestrator ──▶ Agents │
   (text/voice)   │              │               │                    │
                  ▼              ▼               ▼                    │
        ┌──────────────────────────────────────────────┐             │
        │        LEVEL 5 INTERNAL MODEL GATEWAY         │◀────────────┘
        │   (level5/llm/gateway.py)                     │  bare model calls
        │   routes by class, capability and health      │
        └───────────────┬───────────────┬───────────────┘
                        │               │
        ┌───────────────▼──┐   ┌────────▼─────────────┐   ┌──────────────────┐
        │ internal (10)    │   │ development (50)     │   │ external (100+)  │
        │ self-hosted      │   │ OpenHands dev        │   │ OpenAI/Anthropic │
        │ vLLM/llama.cpp/  │   │ gateway (dev aid)    │   │ Google — OFF     │
        │ Ollama — PROD    │   │                      │   │ unless enabled   │
        └───────────────┬──┘   └──────────────────────┘   └──────────────────┘
                        │
        ┌───────────────▼──────────────────────────────────────────────┐
        │ SELF-HOSTED RUNTIME (level5/llm/runtime.py)                   │
        │ engine discovery · start/stop · health · model registry       │
        └──────────────────────────────────────────────────────────────┘

   Memory & retrieval:  level5/knowledge/  (SQLite + BM25, no model)
   Model-free core:     level5/intelligence/fallbacks.py (rules + templates)
```

Independence is enforced in three places:

1. **Gateway routing** (`gateway.py`) — external backends are excluded unless
   the operator enables them, and are never selected after an internal failure.
2. **Client transports** (`client.py`) — the Agent Server transports are dropped
   when the dev gateway is disabled; a bare model call then fails cleanly rather
   than reaching a provider.
3. **Deterministic core** (`fallbacks.py`) — understanding and planning fall
   back to rules when no model answers, so the platform keeps working.

## 3. Module inventory

| Module | Purpose | Model needed? | External needed? |
| --- | --- | --- | --- |
| `level5/llm/gateway.py` | Internal model gateway; class/capability routing | no | no |
| `level5/llm/runtime.py` | Self-hosted runtime lifecycle; model registry/versioning | no | no |
| `level5/llm/providers.py` | Provider registry; availability and capability facts | no | no |
| `level5/llm/client.py` | Bare model calls; internal-first transport selection | for generative text | no |
| `level5/knowledge/store.py` | Project memory; BM25 retrieval | **no** | **no** |
| `level5/intelligence/fallbacks.py` | Deterministic understanding + planning | **no** | **no** |
| `level5/intelligence/understanding.py` | Specification from a request | falls back | no |
| `level5/intelligence/planner.py` | Task graph from a specification | falls back | no |
| `level5/intelligence/research.py` | Research retrieval + cited reports | no (keyless providers) | no |
| `level5/intelligence/problem_solving.py` | Models + execution + verification | for model text | no |
| `level5/orchestrator.py` | Scheduling, execution, memory integration | for generative text | no |
| `level5/agents/registry.py` | Specialist agent roles | no | no |
| `level5/runtime/agent_server.py` | Execution substrate (Agent Server) | yes (execution) | dev only |
| `level5/caber/*` | Building generation + validation | for model text | no |
| `level5/self_improvement.py` | Improvement proposals + review | for model text | no |

## 4. Implementation plan (what was built)

1. **Internal gateway** — a single routing point with explicit backend classes
   (`internal`, `development`, `external`), health probing, and the hard rule
   that external is never an internal fallback.
2. **Self-hosted runtime manager** — discovers `llama-server`/vLLM/Ollama,
   starts and stops the runtime, and keeps a local model registry with declared
   provenance. It downloads nothing and spends nothing.
3. **Local memory and retrieval** — a SQLite knowledge store with Okapi BM25
   ranking, wired into the orchestrator (specification and research are written
   to memory; memory is retrieved before planning).
4. **Deterministic core** — rule-based understanding and per-domain task-graph
   templates, used when no model answers.
5. **Independence test** — `tests/test_independence.py` (20 tests) plus
   `scripts/independence_check.py`, which disables every external provider and
   the dev gateway and runs the core.

## 5. Independence test results

`scripts/independence_check.py`, run with `LEVEL5_ALLOW_EXTERNAL_MODELS=0` and
`LEVEL5_ALLOW_DEV_GATEWAY=0`:

```
[PASS] Reasoning (deterministic understanding + planning): domain=web_app requirements=2 tasks=6
[PASS] Agent coordination (roles + dependency graph): roles=5 deps_ok=True has_edges=True
[PASS] Memory and retrieval (BM25, no model): hits=1 top=Database
[PASS] External providers disabled / no fallback: external_enabled=False dev_gateway_enabled=False external_fallback=False
[PASS] No external reachable for model call: model call correctly failed with no permitted backend
[PASS] Project creation and persistence: stored+reloaded tasks=5
[PASS] Code generation and execution (local): exit=0 output='lines=2 words=4 chars=24'
[PASS] Error recovery (detect defect -> repair -> pass): detected=True repaired_pass=True
[PASS] Model-free fallback engaged in a real call path: domain=mobile_app tasks=6

9/9 core capabilities operated with no external model.
```

**Still requires external services, hardware or infrastructure (reported
honestly):**

- **Generative code authoring with a language model** needs either the
  self-hosted runtime (vLLM/llama.cpp/Ollama on this host) or the Agent Server.
  Neither is installed in this environment, and there is no GPU. Without one,
  the platform plans and executes deterministically but does not author novel
  source with a language model.
- **Keyed research providers** (Tavily, Brave) need credentials. Keyless
  providers (Wikipedia, arXiv, Crossref, GitHub, Stack Exchange) do not.
- **Browser preview of built apps** needs a Node toolchain.

## 6. Staged roadmap toward LEVEL 5's own model

Each stage is gated on the previous one being verified. A self-hosted
third-party model is **not** "our model" and must never be described as one.

| Stage | Goal | Status |
| --- | --- | --- |
| 1 | Independence architecture (gateway, runtime manager, memory, fallbacks) | **done** |
| 2 | Deploy a legally usable open-weight model on hardware we control | not started — no GPU/host provisioned |
| 3 | Own evaluation benchmarks (fixed tasks, deterministic scorer) | partial — suite exists; no model run against it |
| 4 | Fine-tuning pipeline (data → train → eval → register) | not started |
| 5 | Proprietary datasets with recorded rights and consent | not started |
| 6 | Verified experiments improving the model | not started |
| 7 | Progressively replace the foundation model with our own | not started |

Stage 2 requires a decision the founder must make (see §7): which open-weight
model and which host.

## 7. What the founder must provide for stage 2

- **A host with a GPU** (or a CPU-only host that accepts slow inference), with
  enough VRAM/RAM for the chosen model. This environment has no GPU.
- **A chosen open-weight model** with a licence that permits commercial use
  (for example a permissively licensed Llama/Qwen/Mistral variant). The licence
  and provenance are recorded in the model registry by the operator; the
  platform does not infer a licence.
- **A model file on disk**, then register it:

  ```
  python -c "from level5.llm.runtime import get_local_runtime, LocalModel; \
    r = get_local_runtime(); r.registry.register(LocalModel(name='base', \
    path='/models/base.gguf', size_bytes=0, format='gguf', license='...', \
    source='...'))"
  LEVEL5_LOCAL_LLM_MODEL=base python -c "from level5.llm.runtime import get_local_runtime; \
    print(get_local_runtime().start())"
  ```

  Once the runtime answers, it becomes the preferred backend automatically.

## 8. Honest limitations

- No foundation model has been trained. Do not describe LEVEL 5 as having one.
- The deterministic core plans and executes; it does not author novel code.
  That requires a model (self-hosted or the dev gateway).
- The self-hosted runtime manager is verified for discovery and the model
  registry; its start path has not been exercised against a real model because
  no runtime binary or model file exists in this environment.
