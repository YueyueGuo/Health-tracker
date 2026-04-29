# Deployment

You can run the app in either of these ways:

| Approach | Best for |
|----------|----------|
| **[Railway](../README.md#deploy-on-railway)** (Docker, public URL) | HTTPS for your phone, sharing links, no home server. Full variable list and OAuth steps are in the **root [README.md](../README.md)** — this file does not duplicate that. |
| **Mac + Tailscale + `launchd`** (below) | **Private** access: data stays on your Mac, no exposure to the public internet, no Railway account. Still relevant if you want a personal VPN mesh instead of a cloud deploy. |

Both setups run the **same** process: FastAPI serves `/api`, the scheduler, and the built React app from `frontend/dist`.

---

## Mac + Tailscale + launchd (always-on)

This guide runs Health Tracker 24/7 on your Mac with a `launchd` agent and reaches it from your phone over **Tailscale** (no port forwarding).

### Overview

- **Process manager:** macOS `launchd` — starts at login, restarts on crash.
- **Remote access:** Tailscale — devices share a private network.
- **Database:** SQLite at `~/.health-tracker/health_tracker.db` (same as local dev default).

### Prerequisites

1. A Mac you can leave on (sleep is OK; it resumes when the machine wakes).
2. Repo cloned; virtualenv at repo root (required by `install.sh`):
   ```bash
   cd Health-tracker
   python3 -m venv .venv
   .venv/bin/pip install -e .
   ```
3. Node.js (`brew install node`) for the frontend build.
4. `.env` filled out (Strava, Eight Sleep, Whoop, keys — same as [README](../README.md) setup guides).

### Step 1 — Tailscale

**On the Mac**

```bash
brew install --cask tailscale
open -a Tailscale
```

Sign in. MagicDNS name is under [machines](https://login.tailscale.com/admin/machines) (e.g. `my-mac.tailXXXXX.ts.net`), or run:

```bash
tailscale status | head -1
```

**On your phone** — Install the Tailscale app and sign in with the **same** account.

**In `.env`** set (so browser calls from your phone match CORS allow-list):

```bash
TAILSCALE_HOSTNAME=my-mac.tailXXXXX.ts.net
```

Use the hostname you actually type in the browser (MagicDNS name is the usual choice).

### Step 2 — OAuth and `PUBLIC_BASE_URL`

- If you only use **`http://localhost:8000`** on the Mac, you do **not** need `PUBLIC_BASE_URL` for OAuth.
- If you open the app as **`http://<tailscale-host>:8000`** or **`https://<tailscale-host>.ts.net`** (Tailscale Serve), set **exactly that origin** so redirect URIs match:

```bash
PUBLIC_BASE_URL=https://my-mac.tailXXXXX.ts.net
```

No trailing slash. Register the same host in **Strava** and **Whoop** app settings (`…/api/auth/strava/callback` and `…/api/auth/whoop/callback`). After editing `.env`, restart the agent (see [Useful commands](#useful-commands)).

### Step 3 — Install the launchd agent

From the repo root:

```bash
./deploy/install.sh
```

This will:

1. `npm install` and `npm run build` in `frontend/`
2. Install `~/Library/LaunchAgents/com.healthtracker.plist` from `deploy/com.healthtracker.plist.template`
3. `launchctl bootstrap` the agent
4. Create `~/.health-tracker/logs/` for stdout/stderr

### Step 4 — Verify

**On the Mac**

```bash
curl -s http://localhost:8000/api/health
# {"status":"ok","version":"0.1.0"}

tail -f ~/.health-tracker/logs/stdout.log
# Expect: "Scheduler started"
```

**On your phone** (Tailscale on, e.g. cellular): open `http://<TAILSCALE_HOSTNAME>:8000` — the dashboard should load.

### Step 5 — (Optional) HTTPS with Tailscale Serve

For `https://…ts.net` without `:8000`:

```bash
tailscale serve --bg http://localhost:8000
```

Then use that `https` URL everywhere (bookmarks, `PUBLIC_BASE_URL`, provider OAuth redirect URIs). Reset with `tailscale serve reset`.

### Updating after `git pull`

```bash
./deploy/update.sh
```

Pulls, reinstalls Python deps, rebuilds the frontend, restarts the agent.

### Useful commands

```bash
# Status
launchctl print gui/$(id -u)/com.healthtracker | head -30

# Restart (pick up .env / code changes after a pull)
launchctl kickstart -k gui/$(id -u)/com.healthtracker

# Stop until next login or re-install
launchctl bootout gui/$(id -u)/com.healthtracker

# Re-install
./deploy/install.sh

# Logs
tail -f ~/.health-tracker/logs/stdout.log
tail -f ~/.health-tracker/logs/stderr.log
```

### Troubleshooting

**Agent non-zero exit** — Read `~/.health-tracker/logs/stderr.log` (missing dep, bad `.env`, etc.).

**Port 8000 in use** — `pkill -f 'uvicorn backend.main'` or change the port in the plist template / process (advanced).

**API or sync errors from the phone only** — **CORS:** `TAILSCALE_HOSTNAME` in `.env` must match the host you open in the browser (no `http://` prefix in the variable). **OAuth:** if redirects go to `localhost`, set `PUBLIC_BASE_URL` to the URL you use on the phone and restart the agent.

**Mac sleeps** — The process resumes when the Mac wakes. For no sleep on lid-close, change **System Settings → Battery** (behavior varies by Mac model).
