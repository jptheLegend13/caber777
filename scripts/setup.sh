#!/usr/bin/env bash
# Set up LEVEL 5 from a clean checkout.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Backend Python environment"
cd "$ROOT/backend"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required (https://docs.astral.sh/uv/). Falling back to python -m venv."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
else
  uv venv .venv
  uv pip install --python .venv/bin/python -r requirements.txt
fi

echo "==> Frontend dependencies"
cd "$ROOT/frontend"
npm install

echo "==> Build frontend (served by the backend at /)"
npm run build

echo
echo "Setup complete."
echo "  Backend:  scripts/dev.sh"
echo "  Full dev: scripts/dev.sh --frontend"
echo "  Tests:    cd backend && .venv/bin/python -m pytest tests/ -q"
