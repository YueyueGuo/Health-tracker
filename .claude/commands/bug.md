---
description: Run the full agentic bug-fix workflow end-to-end. Investigates, implements the fix, adds a regression test, runs verification, reviews, commits, pushes, opens a PR, and subscribes to PR activity.
---

# /bug — agentic bug workflow

You are the **orchestrator** for a bug fix. The argument is **either**
a free-text bug description (symptom, repro, suspect area) **or** a
reference to a GitHub issue. If empty, ask once.

## Workflow

### Step 0 — Setup

**Parse the argument.** Detect a GitHub issue reference in any of these forms:
- `#<N>` (e.g. `#42`) — assume the current repo.
- `<owner>/<repo>#<N>` (e.g. `YueyueGuo/Health-tracker#42`).
- A full `https://github.com/<owner>/<repo>/issues/<N>` URL.

If matched: call `mcp__github__issue_read` with `method: "get"` to fetch
the issue, then `method: "get_comments"` for additional context. Treat the
issue title + body (+ any clarifying comments) as the bug description.
**Record the issue number** — you'll add `Closes #<N>` to the PR body
in Step 5. If the issue is closed, stop and ask the user whether to
proceed anyway.

Otherwise: treat the argument as free-text bug description.

- Branch: if on `main`, `git checkout -b claude/fix-<slug>-<random>`.
  When the description came from an issue, prefer
  `claude/fix-issue-<N>-<slug>` so the branch name traces back.
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

### Step 4 — Review, QA, security, performance (parallel)
Spawn the applicable agents **in a single message** with multiple
Agent tool uses so they run concurrently:
- `code-reviewer` — always. Pass the diagnosis. Reviewer should
  confirm the regression test exists and exercises the fixed path.
- `qa-verifier` — **only if** the bug had user-visible symptoms
  (broken page, wrong data on dashboard, save flow failing, etc.).
  Skip QA for non-user-visible bugs (a scheduler logging bug, an
  internal data-migration drift). Pass the diagnosis so QA targets
  the exact failing scenario the user reported.
- `security-reviewer` — run unless the fix is doc-only or a pure
  test-file change. Security-relevant bugs (auth, tokens, injection)
  must run it.
- `performance-sentinel` — run if the fix touches a hot path
  (router, sync engine, scheduler, dashboard component). Skip for
  isolated logic bugs in pure utilities.
- `migration-safety-checker` — **only if** the fix added a new
  Alembic revision (rare for bugs, but happens when the bug is a
  schema mismatch).

Merge findings, route by the `Owner:` tag. On `REQUEST_CHANGES` /
`FAIL` / `UNSAFE` / `CONCERNS`: spawn owners **in parallel** in a
single message, re-run **all** reviewers that flagged something.
Loop up to 2 times across the combined review phase. `BLOCK` from
any reviewer → stop and surface to the user.

### Step 5 — Push and open PR

**5a. Promote QA screenshots (only if qa-verifier ran and PASSed).**
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
Only commit on the **final** pass — earlier failed iterations are
discarded so the PR shows what was actually verified at sign-off.

**5b. Push and open the PR.**
- `git push -u origin <branch>`.
- Capture the head commit SHA after the final push — you'll need it for
  absolute image URLs below: `HEAD_SHA=$(git rev-parse HEAD)`.
- Open PR via `mcp__github__create_pull_request`. Title:
  `fix: <one-line symptom>`.
- Body sections:
  - **Summary** — symptom, root cause, fix in 2-3 bullets.
  - **Closes** — `Closes #<N>` if the bug originated from a GitHub issue.
  - **Diagnosis** — link to the diagnosis doc using an absolute GitHub
    URL: `[docs/bugs/<slug>.md](https://github.com/<owner>/<repo>/blob/<branch>/docs/bugs/<slug>.md)`.
    Relative links break in PR bodies because they resolve against
    `/pull/<n>/...` in the rendered page URL.
  - **Test plan** — what a human would run to confirm.
  - **QA screenshots** — only if Step 5a committed any. Embed each as
    an absolute `raw.githubusercontent.com` URL pinned to the head SHA
    so the image survives post-merge branch deletion:
    `![<scenario>](https://raw.githubusercontent.com/<owner>/<repo>/<HEAD_SHA>/docs/qa/<slug>/<file>.png)`.
    Do **NOT** use a relative path like `docs/qa/<slug>/<file>.png` —
    GitHub renders that as `<img src="docs/qa/...">` which the browser
    resolves against the PR page URL (`/pull/<n>/...`) and ends up at
    GitHub's compare route ("there isn't anything to compare"). One
    image per scenario, in the same order as qa-verifier's "Scenarios
    run" table.

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
