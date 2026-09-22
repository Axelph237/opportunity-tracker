#!/usr/bin/env bash
#
# Run the app: one process, one port. FastAPI answers /api and serves the
# compiled interface from frontend/dist for everything else.
#
#   ./scripts/start.sh              # http://localhost:8000
#   ./scripts/start.sh --port 9000
#   ./scripts/start.sh --no-open    # do not launch a browser
#
# For frontend development use ./scripts/dev.sh instead — it adds the Vite dev
# server so changes appear without a rebuild.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

PORT=8000
OPEN=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --no-open) OPEN=0; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[[ -x .venv/bin/python ]] || { echo "No .venv found. Run ./scripts/install.sh first." >&2; exit 1; }

if [[ ! -f frontend/dist/index.html ]]; then
  echo "The interface is not built. Run ./scripts/install.sh, or:" >&2
  echo "  cd frontend && npm run build" >&2
  exit 1
fi

if [[ "$OPEN" == 1 ]]; then
  # Give uvicorn a moment to bind before the browser asks for the page.
  ( sleep 1.5
    if command -v open >/dev/null 2>&1; then open "http://localhost:$PORT"
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://localhost:$PORT"
    fi ) >/dev/null 2>&1 &
fi

echo "Opportunity Tracker  ->  http://localhost:$PORT"
echo "API docs             ->  http://localhost:$PORT/docs"
echo

# --reload is deliberate outside development too: the in-app agent can edit the
# backend, and without it those changes would not take effect until a restart.
exec "$ROOT/.venv/bin/python" -m uvicorn main:app \
  --reload --app-dir backend --host 127.0.0.1 --port "$PORT"
