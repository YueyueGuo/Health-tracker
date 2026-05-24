# `.claude/` — agentic workflow

Specialized agents and slash commands for the Health Tracker project.

## Slash commands (entry points)

| Command | Purpose |
|---------|---------|
| `/feature <desc>` | Full feature workflow: plan → research + migration (parallel) → backend + frontend (parallel) → tests → review → PR → subscribe. |
| `/bug <desc>` | Bug workflow: investigate → fix → regression test → tests → review → PR → subscribe. |

Both commands run in fully-autonomous mode by default. The orchestrator
(top-level Claude in the session) spawns sub-agents and only pauses if
something is genuinely ambiguous or a hard limit is hit (3 test loops,
2 review loops, `BLOCK` verdict).

## Agents

| Agent | Role | Read-only? | Use phase |
|-------|------|------------|-----------|
| `feature-planner` | Produces written implementation plan from a feature description. | Yes | Plan |
| `bug-investigator` | Ranks root-cause hypotheses with file:line evidence. | Yes | Plan |
| `integration-researcher` | Fetches external API docs; answers open questions from the plan. | Yes (WebFetch/Search) | Phase 1 (parallel) |
| `db-migrator` | Writes Alembic revisions, DAG-aware, SQLite+Postgres safe. | No | Phase 1 (parallel) |
| `backend-engineer` | FastAPI / SQLAlchemy / services / clients + tests. | No | Phase 2 (parallel) |
| `frontend-engineer` | React 19 / Vite / TS / Tailwind + typecheck/build. | No | Phase 2 (parallel) |
| `test-runner` | Runs ruff + pytest + npm typecheck + npm build; routes failures. | Yes | Verify |
| `qa-verifier` | Boots backend + frontend, drives golden-path scenarios via Playwright, captures screenshots. Mocks external APIs at the client boundary. | Yes | Review (parallel with code-reviewer) |
| `code-reviewer` | Reviews branch diff against the plan. | Yes | Review (parallel with qa-verifier) |
| `architecture-auditor` | Standalone read-only repo audit (pre-existing). | Yes | Ad hoc |

## Parallelism

The orchestrator spawns parallel work in **a single message with
multiple `Agent` tool uses**. Real parallelism points:

- **Phase 1**: `integration-researcher` ∥ `db-migrator` (only when
  the plan calls for both).
- **Phase 2**: `backend-engineer` ∥ `frontend-engineer` (whenever the
  plan touches both surfaces).
- **Review**: `code-reviewer` ∥ `qa-verifier` (whenever the change
  touches user-visible behavior — see `/feature` Step 5 for the rule).

Sequential by design: planner → phase 1 → phase 2 → tests →
review+QA → PR → subscribe.

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
