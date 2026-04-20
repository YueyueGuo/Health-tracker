# Always-On Deployment (Mac + Tailscale)

This guide sets up Health Tracker to run 24/7 on your Mac with a single `launchd` agent, accessible from your phone and laptop anywhere via Tailscale.

## Overview

- **Process manager**: macOS `launchd` — auto-starts on boot, restarts on crash.
- **Remote access**: Tailscale — private network between your Mac and phone; no port forwarding or public internet exposure.
- **All-in-one**: The FastAPI process runs the web server, the APScheduler, and both bots in its lifespan.

## Prerequisites

1. A Mac you're willing to leave powered on (MacBook in clamshell, Mac mini, etc.). Sleep is fine — it will resume.
2. Repo cloned locally with a working `.venv`:
   ```bash
   cd Health-tracker
   python -m venv .venv
   .venv/bin/pip install -e .
   ```
3. Node.js for the frontend build (`brew install node`).
4. `.env` populated with your credentials (Strava tokens, API keys, bot tokens).

## Step 1 — Install Tailscale

On the Mac:
```bash
brew install --cask tailscale
open -a Tailscale
```
Sign in with your Google/Microsoft/email account.

On your phone:
- iOS: install **Tailscale** from the App Store.
- Android: install **Tailscale** from the Play Store.
- Sign in with the same account as the Mac.

Find your Mac's Tailscale name:
```bash
tailscale status | head -1
# e.g. 100.64.1.2    my-mac    your-name@   macOS   -
```
Or find the MagicDNS name at https://login.tailscale.com/admin/machines — looks like `my-mac.tailXXXXX.ts.net`.

Add it to `.env`:
```
TAILSCALE_HOSTNAME=my-mac.tailXXXXX.ts.net
```

## Step 2 — Install the launchd agent

```bash
./deploy/install.sh
```

This will:
1. `npm install` and `npm run build` in `frontend/` (produces `frontend/dist`)
2. Render `deploy/com.healthtracker.plist.template` into `~/Library/LaunchAgents/com.healthtracker.plist`
3. `launchctl bootstrap` the agent (starts it now and on every login)
4. Create `~/.health-tracker/logs/` for stdout/stderr

The SQLite DB lives at `~/.health-tracker/health_tracker.db`.

## Step 3 — Verify

From the Mac:
```bash
curl http://localhost:8000/api/health
# {"status":"ok","version":"0.1.0"}

tail -f ~/.health-tracker/logs/stdout.log
# Expect: "Scheduler started", "Telegram bot started" (if token set)
```

From your phone (on cellular, not home Wi-Fi):
- Open `http://<tailscale-name>:8000` in Safari/Chrome
- Dashboard should load

## Step 4 — (Optional) HTTPS via Tailscale Serve

If you want clean `https://...ts.net` without the `:8000`:
```bash
tailscale serve --bg http://localhost:8000
```
Now `https://<tailscale-name>.ts.net` works (cert is auto-provisioned).

Disable later with `tailscale serve reset`.

## Updating after a `git pull`

```bash
./deploy/update.sh
```
This pulls, reinstalls Python deps, rebuilds the frontend, and restarts the agent.

## Useful commands

```bash
# Status
launchctl print gui/$(id -u)/com.healthtracker | head -30

# Restart
launchctl kickstart -k gui/$(id -u)/com.healthtracker

# Stop (until next login or manual bootstrap)
launchctl bootout gui/$(id -u)/com.healthtracker

# Re-install / re-enable
./deploy/install.sh

# Logs
tail -f ~/.health-tracker/logs/stdout.log
tail -f ~/.health-tracker/logs/stderr.log
```

## Troubleshooting

**Agent shows up but status code is non-zero** — read `stderr.log`. Usually a missing dep or bad `.env` value.

**Port 8000 already in use** — kill any stray `uvicorn` process: `pkill -f 'uvicorn backend.main'`.

**Dashboard loads but sync fails on phone** — CORS. Confirm `TAILSCALE_HOSTNAME` in `.env` matches the hostname you're opening, then restart: `launchctl kickstart -k gui/$(id -u)/com.healthtracker`.

**Bots not responding** — check `stdout.log` for "Telegram bot started" / Discord warnings. If the token is missing the bot will quietly no-op.

**Mac sleeps and the service stops responding** — `launchd` resumes the process when the Mac wakes. If you want strictly zero downtime, go to System Settings → Battery → Prevent your Mac from automatically sleeping when the display is off.
