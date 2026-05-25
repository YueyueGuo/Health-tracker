---
description: Run the full agentic feature workflow end-to-end. Plans, researches, implements (in parallel), tests, reviews, commits, pushes, opens a PR, and subscribes to PR activity.
---

# /feature — agentic feature workflow

You are the **orchestrator** for a feature delivery. Your job is to
drive the cascade of specialized agents end-to-end, parallelizing where
possible, and finishing with an open PR plus a PR-activity subscription.

The user's feature description is the argument to this command. If
it's empty, ask the user once for a description, then proceed.

## Workflow

### Step 0 — Setup
- Confirm you're on a feature branch. If on `main`, create one:
  `git checkout -b claude/<slug>-<random>` where `<slug>` is derived
  from the feature.
- Read `CLAUDE.md` and `AGENTS.md` if not already in context.

### Step 1 — Plan (single agent)
Spawn the `feature-planner` agent. Pass the full feature description.
When it returns the plan, **persist it to `docs/plans/<slug>.md`**
(the agent prints the plan; you write the file). Commit:
`git add docs/plans/<slug>.md && git commit -m "plan: <slug>"`.

### Step 2 — Phase 1 work (parallel)
Read the plan's "Parallelism plan" section. In a **single message**,
spawn in parallel:
- `integration-researcher` — if and only if Step 4 of the plan
  ("External integration") is non-empty. Pass the open questions.
- `db-migrator` — if and only if Step 7 of the plan ("Migration tasks")
  is non-empty. Pass the migration spec.

Wait for both to finish. If `integration-researcher` flips the plan
(e.g. "this API doesn't exist server-side"), update the plan file and
re-commit before continuing.

### Step 3 — Phase 2 work (parallel)
In a **single message**, spawn in parallel:
- `backend-engineer` — pass the plan + the researcher's brief.
- `frontend-engineer` — pass the plan + any backend contract notes
  from the plan.

Wait for both. Commit each agent's changes in separate commits with
descriptive messages (`feat(backend): ...`, `feat(frontend): ...`).

### Step 4 — Verify (sequential)
Spawn `test-runner`. If it reports failures:
- Route each failure to the right engineer (`backend-engineer`,
  `frontend-engineer`, or `db-migrator`) based on the test-runner's
  suggestion.
- Re-run `test-runner` after the fix.
- Loop up to **3** times. If still failing after 3 rounds, stop and
  surface to the user with a clear summary of what's stuck.

### Step 5 — Review and QA (parallel)
Spawn both agents **in a single message** with two Agent tool uses:
- `code-reviewer` — always.
- `qa-verifier` — **only if** the plan touches user-visible behavior:
  any change under `frontend/`, any new/changed router under
  `backend/routers/`, any sync that updates dashboard data, or the
  plan's "Affected surfaces" explicitly lists a user-facing surface.
  Skip QA for pure refactors, infra-only changes, or migration-only
  PRs.

Merge findings from both into one list, deduplicate by `Files:`, then
route by the `Owner:` tag:
- `APPROVE` + `PASS` (or QA skipped) → continue to Step 6.
- Any `REQUEST_CHANGES` / `FAIL` → group findings by owner, spawn
  owners **in parallel** in a single message (each gets only its own
  findings), then re-run **both** reviewer and (if applicable) QA.
  Loop up to **2** times across review+QA combined.
- `BLOCK` from either → stop and surface to the user.

### Step 6 — Push and open PR

**6a. Promote QA screenshots (only if qa-verifier ran and PASSed).**
The final qa-verifier pass writes screenshots to
`/tmp/qa/screenshots/`. Copy them into the repo so they survive past
the ephemeral container and render in the PR:
```bash
mkdir -p docs/qa/<slug>
rm -f docs/qa/<slug>/*.png 2>/dev/null  # final state only — drop prior iterations
cp /tmp/qa/screenshots/*.png docs/qa/<slug>/ 2>/dev/null || true
git add docs/qa/<slug>
git diff --cached --quiet || git commit -m "qa: attach final-state screenshots for <slug>"
```

**6b. Push and open the PR.**
- Stage any final fixes, commit, push: `git push -u origin <branch>`.
- Open a PR via `mcp__github__create_pull_request` against `main`.
  Title: short, imperative.
- Body sections:
  - **Summary** — what changed in 3-5 bullets.
  - **Plan** — link to `docs/plans/<slug>.md`.
  - **Test plan** — checklist of smoke tests a human would run.
  - **QA screenshots** — only if Step 6a committed any. Embed each as
    `![<scenario>](docs/qa/<slug>/<file>.png)` so GitHub renders them
    inline. One per scenario, in the same order as qa-verifier's
    "Scenarios run" table.

### Step 7 — Subscribe to PR activity
Call `mcp__github__subscribe_pr_activity` with the new PR number so
this session auto-responds to CI failures and review comments.

### Step 8 — Hand off for merge approval
End your turn with a single, action-oriented message containing
**exactly** this shape so the web/mobile push tells the user what to do:

```
PR #<n> ready: <title>
<URL>

CI: <pending | green | red>
Plan: docs/plans/<slug>.md

Reply with one of:
  • `merge`           — squash-merge and close the branch
  • `changes: <text>` — route the changes back through the agents
  • `hold`            — leave open, I'll come back to it
```

Then end the turn. Do not poll.

**When the user replies in this session:**
- `merge` (or `go ahead`, `ship it`, equivalent) → call
  `mcp__github__merge_pull_request` with `merge_method: "squash"`,
  then `unsubscribe_pr_activity`, then confirm in one line.
- `changes: <text>` → treat `<text>` as a new mini-spec; route to the
  relevant engineer agent(s) in parallel; on completion, push and
  reply "updated — re-review or merge?"
- `hold` → unsubscribe, acknowledge in one line, end.

**When PR-activity events arrive while waiting:**
- CI green and the user hasn't replied yet → post a one-line nudge:
  `"CI green on PR #<n> — say `merge` to ship."` Then end turn again.
- CI red → diagnose, route to the right engineer, push the fix, post
  a one-line status. Do not require user input for CI fixes.
- Reviewer comment → investigate and either fix (if unambiguous) or
  ask the user via `AskUserQuestion` if ambiguous.

## Parallelism rules
- Step 2 and Step 3 are the parallelism points. Always spawn the
  parallel agents in a **single message** with multiple `Agent` tool
  uses so they truly run concurrently.
- Never spawn two agents that edit the same files concurrently.
- Sequential by design: planner → phase 1 → phase 2 → tests → review → PR.

## Communication rules
- Brief status messages between steps ("plan done, spawning backend +
  frontend in parallel"). One sentence each. No long narration.
- If anything is genuinely ambiguous (auth choice that materially
  changes scope, destructive migration question), use `AskUserQuestion`.
  Otherwise: keep moving — the user picked fully autonomous mode.
- On unrecoverable failure (3 test loops, 2 review loops, BLOCK
  verdict, network outage on a required external doc), stop and
  summarize state in plain English.

## Branch + commit hygiene
- One branch per feature: `claude/<slug>-<short-suffix>`.
- Small, descriptive commits. No `WIP`. No `--no-verify`.
- Never push to `main`. Never force-push without explicit user
  permission.

$ARGUMENTS
