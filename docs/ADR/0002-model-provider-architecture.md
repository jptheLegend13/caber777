# ADR 0002 — Model and provider architecture

- **Status:** Accepted
- **Date:** 2026-11-08

## Decision

Keep the model layer behind one interface (`backend/level5/llm/client.py`) with a
single OpenAI-compatible chat path, and resolve the endpoint from configuration:

| Setting | Default | Meaning |
|---|---|---|
| `LEVEL5_AGENT_SERVER_URL` | `http://127.0.0.1:60000` | Agent Server; also hosts the model gateway |
| `LEVEL5_LLM_GATEWAY_URL` | `{agent_server_url}/v1` | OpenAI-compatible endpoint |
| `LEVEL5_LLM_MODEL` | `openhands_Default` | Model id sent to the gateway |
| `LEVEL5_LLM_API_KEY` | session key | Falls back to `SESSION_API_KEY` |

Every provider that speaks the OpenAI Chat Completions protocol — OpenAI,
Anthropic via a compatible proxy, Google, open-weight servers (vLLM, Ollama,
llama.cpp), and the OpenHands gateway — works through this one adapter.

## Rationale

- The directive forbids hardcoding the product around one model. A single
  protocol-level adapter keeps provider choice a configuration decision.
- The Agent Server already exposes a working gateway (`/v1`) authenticated with
  the session key, which is the path that is available in this environment.
- The engine never fabricates model identity or capabilities: `LLMUsage` records
  real token counts returned by the provider, and `chat_json` records failures
  rather than inventing a plausible answer.

## Consequences

- Model capability differences are handled by the caller choosing a model and by
  the structured-output contract (`chat_json`), which tolerates fenced or
  prose-wrapped JSON via `parse_json_loose`.
- Provider-specific features (native tool calling, extended thinking) are not
  exposed yet; they would be added as capability flags on the client rather than
  as new code paths in the intelligence layer.
