---
description: Run the full agentic bug-fix workflow end-to-end. Investigates, implements the fix, adds a regression test, runs verification, reviews, commits, pushes, opens a PR, and subscribes to PR activity.
---

# /bug — agentic bug workflow

You are the **orchestrator** for a bug fix. The user's bug description
(symptom, repro, suspect area) is the argument. If empty, ask once.

## Workflow

### Step 0 — Setup
- Branch: if on `main`, `git checkout -b claude/fix-<slug>-<random>`.
- Read `CLAUDE.md` and `AGENTS.md` if not in context.

### Step 1 — Investigate
Spawn `bug-investigator`. Pass the bug description. When it returns
the diagnosis, persist it to `docs/bugs/<slug>.md` and commit:
`git add docs/bugs/<slug>.md && git commit -m "diagnose: <slug>"`.

### Step 2 — Fix (often a single agent, sometimes parallel)
From the diagnosis's "Recommended fix" section, determine which
engineer owns the fix:
- Backend / DB / service / sync → `backend-engineer`.
- React / TS / page / API client → `frontend-engineer`.
- Schema → `db-migrator`.

If the fix spans backend + frontend (e.g. API contract change), spawn
both **in parallel** in a single message. Otherwise, just one.

Each engineer must add a **regression test** that fails on `main` and
passes on this branch. The investigator's diagnosis specifies what
the test should assert.

Commit each agent's changes separately: `fix(backend): ...`,
`fix(frontend): ...`.

### Step 3 — Verify
Spawn `test-runner`. Loop up to 3 times on failure (same rules as
`/feature` Step 4).

### Step 4 — Review
Spawn `code-reviewer`. Pass the diagnosis. Reviewer should especially
confirm the regression test exists and exercises the fixed path.
On `REQUEST_CHANGES`: route by the `Owner:` tag on each finding,
spawn owners **in parallel** in a single message, re-review. Loop up
to 2 times.

### Step 5 — Push and open PR
- `git push -u origin <branch>`.
- Open PR via `mcp__github__create_pull_request`. Title:
  `fix: <one-line symptom>`. Body: symptom, root cause, fix summary,
  link to `docs/bugs/<slug>.md`, test plan.

### Step 6 — Subscribe to PR activity
`mcp__github__subscribe_pr_activity` with the PR number.

### Step 7 — Hand off for merge approval
Same hand-off pattern as `/feature` Step 8 — see that file for the
exact message shape and the merge/changes/hold reply handling. End
your turn after posting it. Do not poll.

## Rules
- Smallest fix possible. Out-of-scope cleanups the investigator
  spotted go in a follow-up issue or a separate `/feature` run.
- Always add a regression test. If you can't, escalate to the user.
- Same parallelism, branch, and commit rules as `/feature`.

$ARGUMENTS
