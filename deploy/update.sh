#!/usr/bin/env bash
# Pull latest code, rebuild frontend + reinstall deps, and restart the agent.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "==> git pull"
git pull --ff-only

echo "==> pip install -e ."
"$REPO_DIR/.venv/bin/pip" install -e . --quiet

echo "==> npm install + build"
(cd "$REPO_DIR/frontend" && npm install && npm run build)

UID_NUM=$(id -u)
echo "==> Restarting launchd agent"
launchctl kickstart -k "gui/$UID_NUM/com.healthtracker"

echo "==> Done. Tail logs with:"
echo "    tail -f $HOME/.health-tracker/logs/stdout.log $HOME/.health-tracker/logs/stderr.log"
