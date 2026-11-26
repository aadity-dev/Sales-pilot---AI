#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${PORT:-8008}"

if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi
source .venv/bin/activate

if ! python -c "import fastapi, uvicorn, multipart, dotenv" 2>/dev/null; then
  pip install -r requirements.txt
fi

echo "Starting SalesPilot AI at http://127.0.0.1:${PORT}"
exec uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$PORT"
