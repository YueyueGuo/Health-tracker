#!/usr/bin/env bash
# First-time install of the Health Tracker launchd agent on macOS.
# Builds the frontend, renders the plist template, and bootstraps the agent.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_NAME="com.healthtracker.plist"
PLIST_SRC="$REPO_DIR/deploy/com.healthtracker.plist.template"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"
LOG_DIR="$HOME/.health-tracker/logs"

echo "==> Health Tracker install"
echo "    Repo:  $REPO_DIR"
echo "    Plist: $PLIST_DST"

if [[ ! -d "$REPO_DIR/.venv" ]]; then
    echo "ERROR: $REPO_DIR/.venv not found. Create one with: python -m venv .venv && .venv/bin/pip install -e ." >&2
    exit 1
fi

echo "==> Building frontend"
(cd "$REPO_DIR/frontend" && npm install && npm run build)

echo "==> Preparing log directory: $LOG_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "$HOME/Library/LaunchAgents"

echo "==> Rendering plist"
sed -e "s|{{REPO_DIR}}|$REPO_DIR|g" \
    -e "s|{{HOME}}|$HOME|g" \
    "$PLIST_SRC" > "$PLIST_DST"

UID_NUM=$(id -u)
if launchctl print "gui/$UID_NUM/com.healthtracker" >/dev/null 2>&1; then
    echo "==> Agent already loaded; bootout + bootstrap for fresh config"
    launchctl bootout "gui/$UID_NUM/com.healthtracker" || true
fi

echo "==> Bootstrapping agent"
launchctl bootstrap "gui/$UID_NUM" "$PLIST_DST"
launchctl enable "gui/$UID_NUM/com.healthtracker"

echo
echo "Done. Useful commands:"
echo "  Check status:   launchctl print gui/$UID_NUM/com.healthtracker | head -30"
echo "  Tail logs:      tail -f $LOG_DIR/stdout.log $LOG_DIR/stderr.log"
echo "  Restart:        launchctl kickstart -k gui/$UID_NUM/com.healthtracker"
echo "  Stop:           launchctl bootout gui/$UID_NUM/com.healthtracker"
echo "  Health check:   curl http://localhost:8000/api/health"
