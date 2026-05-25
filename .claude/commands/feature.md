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

### Step 0.5 — Choose workflow lane

Before invoking the planner, decide whether this change qualifies for
the **fast path** (skips the planner + the entire review cascade).

**Eligible only when ALL hold:**
- One layer only — frontend OR backend, not both.
- ≤ 2 production files expected to change (excluding tests).
- No DB migration, no new dependency, no new external API integration.
- No new public surface (route, exported function, schema field).
- Change is a copy/label/styling tweak, a small formatter or prop
  change, or a localized refactor.
- User signal: phrasing like "minor", "tiny", "small", "be strategic
  about agents", "skip the cascade" — **or** the description itself
  is unambiguously trivial (e.g. "rename heading X to Y").

If any condition fails, take the full lane (Steps 1-5 as written).

**Fast-path workflow (replaces Steps 1-5):**
1. Make the edit yourself, or spawn a single `frontend-engineer` /
   `backend-engineer` if the work is enough to warrant isolating its
   context. No `feature-planner`, no `docs/plans/<slug>.md`.
2. Run typecheck + the relevant test suite inline via Bash. If
   failures appear, fix inline (one retry). If they're non-trivial,
   drop the fast path and resume the full lane from Step 4.
3. Commit with a conventional message (`feat(frontend): ...` etc.).
4. Skip Step 5's review cascade. Jump straight to Step 6 (push + PR).

**PR body changes for the fast path:**
- Replace the **Plan** section with a one-line **Scope note**
  explaining why the fast path was used and how you verified locally
  (e.g. "Single-component label change — skipped planner + review
  cascade. Verified with `npm run typecheck` + full vitest suite.").
- Test plan + QA screenshot rules unchanged.

**Announce the lane in one line before proceeding**, e.g.:
> Fast path: single-component label change, no backend/DB. Skipping planner + review cascade.

**Escalation:** if mid-flight you discover a migration, a route /
public-surface change, or > 2-file scope, drop the fast path and
restart from Step 1 (planner). Tell the user in one line.

### Step 1 — Plan (single agent)
Spawn the `feature-planner` agent. Pass the full feature description.
When it returns the plan, **persist it to `docs/plans/<slug>.md`**
(the agent prints the plan; you write the file). Commit:
`git add docs/plans/<slug>.md && git commit -m "plan: <slug>"`.

### Step 2 — Phase 1 work (parallel)
Read the plan's "Parallelism plan" section.

**Scope preamble.** Before spawning, post one line stating which Phase 1 agents will run and why each available agent is being skipped, e.g.:
> Phase 1: db-migrator (Section 7 non-empty, risk=trivial). Skipping integration-researcher (Section 4 empty), migration-safety-checker (will re-check post-author).

In a **single message**, spawn in parallel:
- `integration-researcher` — if and only if Step 4 of the plan
  ("External integration") is non-empty. Pass the open questions.
- `db-migrator` — if and only if Step 7 of the plan ("Migration tasks")
  is non-empty. Pass the migration spec.

Wait for both to finish. If `integration-researcher` flips the plan
(e.g. "this API doesn't exist server-side"), update the plan file and
re-commit before continuing.

**If `db-migrator` ran**, decide whether `migration-safety-checker` is
warranted. Inspect what was authored:

```bash
NEW_REVS=$(git diff --name-only origin/main...HEAD -- alembic/versions/)
echo "--- New revisions:"; echo "$NEW_REVS"
echo "--- Op calls:"
grep -hE 'op\.(create_table|add_column|alter_column|create_index|create_foreign_key|execute|drop_|rename_)' $NEW_REVS 2>/dev/null
```

**Skip migration-safety-checker** when *all* of the following hold:
- The new revisions contain at least one `op.create_table()` call.
- Every `op.add_column()` / `op.create_index()` / `op.create_foreign_key()` targets a table also created in these same revisions (i.e. empty in production).
- No `op.alter_column()`, `op.execute()` raw SQL, `op.drop_*`, or `op.rename_*` appears anywhere.
- The plan's Section 7 "Risk" line is `trivial` (planner's hint must agree — if it says `nontrivial`, run the agent even if the ops look clean).

Otherwise spawn `migration-safety-checker` sequentially. On `UNSAFE`, route findings back to `db-migrator` and re-audit; loop up to **2** times. On `BLOCK`, stop and surface to the user. On `SAFE`, continue to Step 3.

State the skip/run decision in one line before proceeding.

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

### Step 5 — Review (parallel, scoped)

**Scope analysis.** Before spawning, run a fast pre-check on the diff
to decide which review agents are warranted:

```bash
git diff --name-only origin/main...HEAD > /tmp/_changed.txt
git diff --shortstat origin/main...HEAD
```

Then post **one line** announcing which agents will spawn and the
one-phrase reason any default agent is being skipped, e.g.:
> Review: code-reviewer + qa-verifier + security-reviewer. Skipping perf-sentinel (no perf signals), migration-safety (new tables only).

Agents and triggers:

- `code-reviewer` — **always**.
- `qa-verifier` — **run if** the plan touches user-visible behavior:
  any change under `frontend/`, any new/changed router under
  `backend/routers/`, any sync that updates dashboard data, or the
  plan's "Affected surfaces" explicitly lists a user-facing surface.
  Skip for pure refactors, infra-only changes, or migration-only PRs.
- `security-reviewer` — **skip only** for doc-only diffs (changes
  confined to `docs/`, `*.md`, or comments). Otherwise run.
- `performance-sentinel` — **run if** the diff touches **any** of
  these signals (otherwise skip with reason `no perf signals`):
  - `backend/scheduler.py`
  - `backend/services/*sync*.py` (any sync engine)
  - `backend/services/insights.py`, `llm_providers.py`, `insight_prompts.py`
  - `backend/clients/` (rate-limit / async hygiene)
  - `frontend/package.json` or `frontend/package-lock.json` (new deps)
  - Total non-test diff size > 500 lines added
- `migration-safety-checker` — **run if** new revisions exist under
  `alembic/versions/` **and** Step 2's skip rule did *not* apply (i.e.
  the migration is nontrivial: alters existing tables, backfills,
  raw SQL, drops, renames, or planner flagged `Risk: nontrivial`).
  Re-audit here because Phase 2 may have touched models in ways that
  affect the migration. Skip otherwise.

Spawn the applicable agents **in a single message** with multiple
Agent tool uses so they run concurrently.

Merge findings from all reviewers into one list, deduplicate by
`Files:`, then route by the `Owner:` tag:
- All `APPROVE` / `PASS` / `SAFE` / `OK` (or skipped) → Step 6.
- Any `REQUEST_CHANGES` / `FAIL` / `UNSAFE` / `CONCERNS` → group
  findings by owner, spawn owners **in parallel** in a single message
  (each gets only its own findings), then re-run **all** reviewers
  that flagged something. Loop up to **2** times across the combined
  review phase.
- `BLOCK` from any → stop and surface to the user.

Severity gate: `performance-sentinel` `LOW` findings and
`security-reviewer` `LOW` findings on a `CONCERNS`-only verdict may
be deferred to a follow-up issue rather than fixed in this PR — call
that out in the PR body.

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
- Capture the head commit SHA *after* the final push — you'll need it
  for absolute image URLs below: `HEAD_SHA=$(git rev-parse HEAD)`.
- Open a PR via `mcp__github__create_pull_request` against `main`.
  Title: short, imperative.
- Body sections:
  - **Summary** — what changed in 3-5 bullets.
  - **Plan** — link to the plan file using an absolute GitHub URL:
    `[docs/plans/<slug>.md](https://github.com/<owner>/<repo>/blob/<branch>/docs/plans/<slug>.md)`.
    Relative links in PR bodies resolve against `/pull/<n>/...` in the
    rendered page URL and break, so always use absolute URLs.
  - **Test plan** — checklist of smoke tests a human would run.
  - **QA screenshots** — only if Step 6a committed any. Embed each as
    an absolute `raw.githubusercontent.com` URL pinned to the head SHA
    so the image survives the post-merge branch deletion:
    `![<scenario>](https://raw.githubusercontent.com/<owner>/<repo>/<HEAD_SHA>/docs/qa/<slug>/<file>.png)`.
    Do **NOT** use a relative path like `docs/qa/<slug>/<file>.png` —
    GitHub renders that as `<img src="docs/qa/...">` which the browser
    resolves against the PR page URL (`/pull/<n>/...`) and ends up at
    GitHub's compare route ("there isn't anything to compare"). One
    image per scenario, in the same order as qa-verifier's "Scenarios
    run" table.

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
- Step 3 and Step 5 are the parallelism points. Always spawn the
  parallel agents in a **single message** with multiple `Agent` tool
  uses so they truly run concurrently.
- Step 2 has one mid-step sequential dependency:
  `migration-safety-checker` runs after `db-migrator` (it can't audit
  work that hasn't happened yet).
- Never spawn two agents that edit the same files concurrently. All
  review-phase agents are read-only and safely parallel.
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
