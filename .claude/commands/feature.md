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

### Step 5 — Review
Spawn `code-reviewer`. If verdict is:
- `APPROVE` → continue.
- `REQUEST_CHANGES` → route must-fix items back to the right engineer,
  then re-run `code-reviewer`. Loop up to **2** times.
- `BLOCK` → stop and surface to the user.

### Step 6 — Push and open PR
- Stage any final fixes, commit, push: `git push -u origin <branch>`.
- Open a PR via `mcp__github__create_pull_request` against `main`.
  Title: short, imperative. Body: link to `docs/plans/<slug>.md` and
  summarize what changed in 3-5 bullets. Test plan: a checklist of the
  smoke tests a human would run.

### Step 7 — Subscribe to PR activity
Call `mcp__github__subscribe_pr_activity` with the new PR number so
this session auto-responds to CI failures and review comments.

End your turn after subscribing. Do not poll. Events will wake the
session.

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
