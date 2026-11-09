#!/usr/bin/env bash
# Start the LEVEL 5 backend and (optionally) the frontend dev server.
#
# Usage: scripts/dev.sh [--frontend]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${LEVEL5_PORT:-12000}"
FRONTEND_PORT="${LEVEL5_FRONTEND_PORT:-5173}"

if [[ ! -d "$ROOT/backend/.venv" ]]; then
  echo "No backend venv found. Run scripts/setup.sh first." >&2
  exit 1
fi

# The Agent Server session key is needed to reach the local gateway.
if [[ -z "${SESSION_API_KEY:-}" && -f "$HOME/.oh_session_key" ]]; then
  export SESSION_API_KEY="$(cat "$HOME/.oh_session_key")"
fi

echo "Starting LEVEL 5 backend on :$BACKEND_PORT"
cd "$ROOT/backend"
nohup .venv/bin/python -m uvicorn level5.api.app:app \
  --host 0.0.0.0 --port "$BACKEND_PORT" \
  > /tmp/level5-backend.log 2>&1 &
echo "  pid $! — logs: /tmp/level5-backend.log"

if [[ "${1:-}" == "--frontend" ]]; then
  echo "Starting frontend dev server on :$FRONTEND_PORT"
  cd "$ROOT/frontend"
  LEVEL5_BACKEND_URL="http://127.0.0.1:$BACKEND_PORT" \
    nohup npm run dev -- --port "$FRONTEND_PORT" > /tmp/level5-frontend.log 2>&1 &
  echo "  pid $! — logs: /tmp/level5-frontend.log"
fi

sleep 4
echo "Health:"
curl -sS "http://127.0.0.1:$BACKEND_PORT/api/health" || echo "  (backend not responding yet)"
