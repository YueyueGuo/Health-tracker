# `.claude/` — agentic workflow

Specialized agents and slash commands for the Health Tracker project.

## Slash commands (entry points)

| Command | Purpose |
|---------|---------|
| `/spec <rough idea>` | Refinement workflow: draft → interactive Q&A → final spec at `docs/specs/<slug>.md`. Stops at a spec file — does **not** run planner or implementation. Hand off to `/feature` when ready. |
| `/feature <desc \| spec path>` | Full feature workflow: plan → research + migration (parallel) → backend + frontend (parallel) → tests → review → PR → subscribe. Accepts a free-text description or a path to a spec file produced by `/spec`. |
| `/bug <desc \| #N \| issue-url>` | Bug workflow: investigate → fix → regression test → tests → review → PR → subscribe. Accepts a free-text description **or** a GitHub issue reference (`#42`, `owner/repo#42`, or a github.com issue URL) — the orchestrator fetches the issue and uses it as the bug description, then adds `Closes #N` to the PR. |

Both commands run in fully-autonomous mode by default. The orchestrator
(top-level Claude in the session) spawns sub-agents and only pauses if
something is genuinely ambiguous or a hard limit is hit (3 test loops,
2 review loops, `BLOCK` verdict).

## Agents

| Agent | Role | Read-only? | Use phase |
|-------|------|------------|-----------|
| `product-spec` | Refines a rough feature idea into a concrete spec via an interactive Q&A loop. | Yes | Spec (pre-Plan) |
| `feature-planner` | Produces written implementation plan from a feature description or refined spec. | Yes | Plan |
| `bug-investigator` | Ranks root-cause hypotheses with file:line evidence. | Yes | Plan |
| `integration-researcher` | Fetches external API docs; answers open questions from the plan. | Yes (WebFetch/Search) | Phase 1 (parallel) |
| `db-migrator` | Writes Alembic revisions, DAG-aware, SQLite+Postgres safe. | No | Phase 1 (parallel) |
| `backend-engineer` | FastAPI / SQLAlchemy / services / clients + tests. | No | Phase 2 (parallel) |
| `frontend-engineer` | React 19 / Vite / TS / Tailwind + typecheck/build. | No | Phase 2 (parallel) |
| `test-runner` | Runs ruff + pytest + npm typecheck + npm build; routes failures. | Yes | Verify |
| `migration-safety-checker` | Audits new Alembic revisions for Postgres production safety (drift, locks, NOT NULL hazards, backfill). | Yes | Phase 1 (sequential after `db-migrator`); re-run in Review if migrations exist |
| `qa-verifier` | Boots backend + frontend, drives golden-path scenarios via Playwright, captures screenshots, runs axe-core a11y scan on each page. Mocks external APIs at the client boundary. | Yes | Review (parallel) |
| `code-reviewer` | Reviews branch diff against the plan for correctness + conventions + scope. | Yes | Review (parallel) |
| `security-reviewer` | Reviews diff for secrets, auth/authz, injection, unsafe deserialization, dep CVEs, prompt injection. | Yes | Review (parallel) |
| `performance-sentinel` | Inspects diff for N+1, missing indexes, blocking I/O in async, frontend bundle bloat / re-renders. | Yes | Review (parallel) |
| `architecture-auditor` | Standalone read-only repo audit (pre-existing). | Yes | Ad hoc |

## Parallelism

The orchestrator spawns parallel work in **a single message with
multiple `Agent` tool uses**. Real parallelism points:

- **Phase 1**: `integration-researcher` ∥ `db-migrator` (only when
  the plan calls for both). `migration-safety-checker` then runs
  *sequentially* after `db-migrator`, **but only when the migration
  is nontrivial** (see triggering rules below).
- **Phase 2**: `backend-engineer` ∥ `frontend-engineer` (whenever the
  plan touches both surfaces).
- **Review**: `code-reviewer` ∥ `qa-verifier` ∥ `security-reviewer`
  ∥ `performance-sentinel` ∥ `migration-safety-checker` — all
  read-only, all safely concurrent, but each is *individually gated*
  by trigger rules. The orchestrator posts a one-line scope-analysis
  preamble before spawning, naming the agents that will run and the
  reason for any skip.

Sequential by design: planner → phase 1 (incl. migration audit when
warranted) → phase 2 → tests → review (multi-agent parallel) → PR →
subscribe.

## Triggering rules (when each review-phase agent runs)

The orchestrator runs the **minimum set of agents** needed for the
diff. Don't blanket-spawn — articulate the choice in the scope
preamble.

| Agent | Runs when | Skips when |
|-------|-----------|------------|
| `code-reviewer` | Always | Never |
| `qa-verifier` | Diff touches user-visible surface: `frontend/`, new/changed `backend/routers/`, sync engine that feeds the dashboard, or plan's "Affected surfaces" lists a user-facing surface | Pure refactors, infra-only, migration-only PRs |
| `security-reviewer` | Any non-doc, non-test diff | Doc-only or test-only diffs |
| `performance-sentinel` | Diff touches `backend/scheduler.py`, `backend/services/*sync*.py`, `backend/services/insights.py` / `llm_providers.py` / `insight_prompts.py`, `backend/clients/`, `frontend/package.json`, or non-test diff > 500 lines added | All other diffs (most CRUD / page work) |
| `migration-safety-checker` | New revisions exist under `alembic/versions/` **and** any of: `op.alter_column`, `op.execute`, `op.drop_*`, `op.rename_*`, an op targeting a table that already exists on `main`, or planner flagged `Risk: nontrivial` | New-table-only migrations (everything operates on tables also being created in this same set of revisions) — `Risk: trivial` from the planner |

For `migration-safety-checker`, the orchestrator's pre-spawn check
greps the new alembic revisions for op-call names and cross-checks
against the planner's `Risk:` line. See `/feature` Step 2 for the
exact bash snippet.

## Adding a new agent

1. Drop a markdown file in `.claude/agents/<name>.md` with frontmatter:
   ```yaml
   ---
   name: <name>
   description: <one-paragraph trigger description>
   tools: Read, Grep, Glob, Bash, [Edit, Write, WebFetch, WebSearch]
   model: opus            # optional; inherits parent if omitted
   permissionMode: plan   # optional; for read-only agents
   memory: project
   ---
   ```
2. Body: clear system prompt. Be specific about *how to start*,
   *conventions to follow*, *definition of done*, and *rules*.
3. Wire it into a slash command if it belongs in the default flow.

## PR-activity follow-up

After opening a PR, the orchestrator calls
`mcp__github__subscribe_pr_activity` so this session auto-responds to:
- CI failures (dispatches the right engineer)
- Review comments (interprets and routes)

End the turn after subscribing; never poll.

## QA screenshots in PRs

When `qa-verifier` runs and returns `PASS` on the final review loop,
the orchestrator promotes its screenshots from `/tmp/qa/screenshots/`
into `docs/qa/<slug>/` on the branch and embeds them in the PR body
via relative markdown. Only the **final state** is committed —
earlier failed iterations are not retained. This gives the human
reviewer a visual record of what was checked without bloating the
repo with intermediate runs.

`qa-verifier` must use stable, kebab-case screenshot filenames (e.g.
`dashboard-loaded.png`) so re-runs overwrite rather than accumulate.
