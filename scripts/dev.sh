#!/usr/bin/env bash
# Start the API and the UI together and stop both on Ctrl-C.
#
# Running only one of them is the usual cause of "500" on every table: the Vite
# dev server proxies /api to :8000, so with the API down every request fails.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

if [[ ! -x .venv/bin/python ]]; then
  echo "No .venv found. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

cleanup() { trap - INT TERM EXIT; kill 0 2>/dev/null || true; }
trap cleanup INT TERM EXIT

"$ROOT/.venv/bin/python" -m uvicorn main:app --reload --app-dir backend --port 8000 &
(cd frontend && npm run dev) &

echo "API  http://localhost:8000/docs"
echo "UI   http://localhost:5173"
wait
