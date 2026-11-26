#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi
source .venv/bin/activate

if ! python -c "import pytest, httpx, fastapi" 2>/dev/null; then
  python -m pip install -r requirements-dev.txt
fi

python -m pytest -v
python -m compileall -q backend
if command -v node >/dev/null 2>&1; then
  node --check backend/app/static/app.js
fi
