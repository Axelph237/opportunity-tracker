#!/usr/bin/env bash
# Cron entrypoint: hands run_scrape.md to Claude Code as a headless prompt.
#
# Install with `crontab -e` (twice daily at 8am and 6pm):
#   0 8,18 * * * /path/to/opportunity-tracker/scripts/run_scrape.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p logs
LOG_FILE="logs/scrape-$(date +%Y%m%d-%H%M%S).log"

# cron runs with a minimal PATH; make sure the usual install locations are on it.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

{
  echo "=== scrape run $(date -Iseconds) ==="
  # --allowedTools pre-approves exactly what the task file needs. Do not add
  # --permission-mode dontAsk here: it denies Bash outright, even when allowed.
  claude -p "$(cat run_scrape.md)" \
    --allowedTools "Bash(.venv/bin/python:*)" "Read" "Glob" "Grep"
  echo "=== finished $(date -Iseconds) ==="
} >>"$LOG_FILE" 2>&1

# Keep the 30 most recent logs.
ls -1t logs/scrape-*.log 2>/dev/null | tail -n +31 | xargs -r rm -f
