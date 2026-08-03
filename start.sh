#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PYTHONPATH="$ROOT/src"

HOST="${RESUALIGN_HOST:-127.0.0.1}"
PORT="${RESUALIGN_PORT:-8000}"

if [ ! -f "$ROOT/.env" ]; then
  echo "Warning: no .env found. Copy .env.example to .env and set DEEPSEEK_API_KEY for LLM features." >&2
fi

echo "ResuAlign starting at http://${HOST}:${PORT}"
exec python -m uvicorn resualign.api:app --host "$HOST" --port "$PORT" --app-dir "$ROOT/src"
