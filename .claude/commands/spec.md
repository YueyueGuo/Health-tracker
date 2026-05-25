---
description: Refine a rough feature idea into a concrete spec. Spawns product-spec agent in an interactive Q&A loop, then commits docs/specs/<slug>.md so it's ready to hand off to /feature.
---

# /spec — feature refinement workflow

You are the **orchestrator** for spec refinement. Your job is to turn
a rough feature idea into a concrete spec the planner can act on,
using a short interactive loop with the user.

The argument is the user's rough idea. If empty, ask once for a
one-paragraph description.

## Workflow

### Step 0 — Setup
- If on `main`, create a spec branch: `git checkout -b claude/spec-<slug>-<random>`
  where `<slug>` is derived from the idea.
- Read `CLAUDE.md` and `AGENTS.md` if not in context.

### Step 1 — Draft (single agent, Mode A)
Spawn `product-spec` with `mode: draft` and the rough idea. Agent
returns:
- A draft spec following its template.
- A numbered list of open questions, each multiple-choice with a
  recommendation.

Persist the draft to `docs/specs/<slug>.md` (overwrite on each pass).
Do **not** commit yet — the spec is still incomplete.

### Step 2 — Ask the user
Surface the agent's open questions via `AskUserQuestion`. Rules:
- `AskUserQuestion` takes 1-4 questions per call. If the agent
  returned more than 4, batch into two calls.
- For each question, copy the agent's header (the short label) and
  options verbatim. The agent already marked the recommended option;
  preserve that ordering and the `(Recommended)` suffix in the label.
- Set `multiSelect: false` for all unless the question's text clearly
  asks for multiple answers (e.g. "which of these should v1 include?").

### Step 3 — Refine (single agent, Mode B)
Spawn `product-spec` again with `mode: refine`, passing:
- The draft spec markdown.
- Each question + the user's answer.

Agent returns the final spec with `[OPEN: see Q<n>]` markers
resolved. Overwrite `docs/specs/<slug>.md` with the final version.

If the refined spec **still** has open questions (the agent flagged
new follow-ups), loop back to Step 2 once more. Hard cap: **2 Q&A
rounds total** — after that, commit what you have with the remaining
opens explicit, and surface to the user.

### Step 4 — Commit and push
```bash
git add docs/specs/<slug>.md
git commit -m "spec: <slug>"
git push -u origin claude/spec-<slug>-<random>
```

### Step 5 — Hand off
End your turn with this message shape:

```
Spec ready: docs/specs/<slug>.md
Branch: claude/spec-<slug>-<random>

Reply with one of:
  • `feature`        — kick off /feature on this spec
  • `edit: <text>`   — refine the spec further (re-runs from Step 1
                       with your notes as additional context)
  • `done`           — leave the spec on its branch, I'll come back
```

Then end the turn. Do not poll.

**When the user replies in this session:**
- `feature` (or `plan`, `go`, `ship it`, equivalent) → invoke
  `/feature` with the spec's content as the description. The planner
  reads the markdown file at `docs/specs/<slug>.md` and proceeds
  directly to Phase 1 (no further refinement). The feature branch
  forks from the current spec branch so the spec doc is in the PR.
- `edit: <text>` → pass `<text>` as additional context to a fresh
  `product-spec` run in Mode A (treat as a refinement pass on the
  existing draft, not from-scratch). New Q&A round, new commit on
  the same branch.
- `done` → acknowledge in one line and end. The branch stays open.

## Rules
- Do not run `/feature` automatically. The user must opt in — specs
  are cheap, implementations aren't.
- Do not edit code. `/spec` only writes to `docs/specs/`.
- Keep the loop tight: 1-2 Q&A rounds max. If the user wants deeper
  exploration after that, they can `edit: <text>` to keep iterating.
- One spec per branch. If the idea splits into two features mid-
  refinement, ask the user via `AskUserQuestion` whether to split
  into two `/spec` runs.
- Spec files go in `docs/specs/<slug>.md`. Filename matches the
  branch slug for traceability.

$ARGUMENTS
