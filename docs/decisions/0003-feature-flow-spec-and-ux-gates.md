# 0003. `/feature` Phase 0: human-gated spec + UX mockups before planning

## Status

Accepted — 2026-05-30.

## Context

The `/feature` workflow had a single human checkpoint: the PR gate at
the very end (Step 8). For anything non-trivial, that is the most
expensive place to discover the build went in the wrong direction —
the spec was misread, or the UI isn't what the owner pictured. By then
the planner, both engineers, and the review cascade have already run.

The flow also under-used the planning artifacts it could have had:

- `product-spec` already existed and produces a real product spec, but
  it only ran as the standalone `/spec` command. `/feature` itself
  jumped straight from a free-text description (or a pre-made spec
  path) to the `feature-planner`.
- The only "design" input to the planner and `frontend-engineer` was
  the spec's **text** UX sketch. There were no visual mockups, so
  "what should this look like" was decided implicitly during the build
  and only became visible at the PR gate via `qa-verifier` screenshots
  — i.e. after the fact.

## Decision

Add **Phase 0** to the `/feature` full lane, before the planner, with
two human approval gates:

- **Phase 0a — Spec.** Reuse (not replace) `product-spec` as the PM
  agent. It runs its Mode A/B Q&A loop, the spec is persisted to
  `docs/specs/<slug>.md`, and **Gate 1** stops for the owner to
  `approve` / `changes:`. A spec path passed in from `/spec` is treated
  as already-approved and skips Gate 1.
- **Phase 0b — UX design.** A new `ux-designer` agent turns the
  approved spec into self-contained HTML/CSS mockups for each key
  screen + state (loaded / empty / error), renders them to PNG via
  headless Chromium, and commits them under `docs/design/<slug>/`.
  **Gate 2** surfaces the mockups (PNGs inline via `SendUserFile`) for
  `approve` / `changes:`.

The `feature-planner` then consumes the **approved** spec + mockups, so
planning realizes agreed intent rather than relitigating it. The
`qa-verifier` gained a step that compares the **built** UI against the
approved mockups (structural/intent comparison, not a pixel diff) — so
the loop closes: design intent → build → verify-against-intent.

### Key choices

- **Reuse `product-spec`, don't add a second PM agent.** Two
  spec-owning agents would fight over "what's the spec." The gap was
  invocation, not capability.
- **Mockups are static HTML rendered to PNG.** No external design tool
  in the loop; artifacts render inline in async (web/mobile) review and
  commit cleanly to the repo. If Chromium can't install/run, the agent
  falls back to committing the HTML sources + a note rather than
  failing the whole feature flow.
- **Full lane only.** Phase 0 and Gates 1–2 run only on the full lane.
  The existing fast path (trivial single-layer changes) skips them
  entirely, so small work isn't dragged through PM + UX + two
  approvals.
- **Reuse the existing stop/resume gate pattern.** Gates 1–2 work
  exactly like the PR gate (Step 8): surface artifact, end turn, resume
  on reply. No new mechanism.

## Consequences

- Non-trivial features now have three human checkpoints (spec, mockups,
  PR) instead of one, adding two stop/resume round-trips. This is the
  intended trade: cheap course-correction early vs. expensive rework
  late.
- New artifact directory `docs/design/<slug>/` (PNG mockups + HTML
  sources), parallel to `docs/specs/` and `docs/qa/`.
- `qa-verifier` may emit a new finding type — divergence from the
  approved mockup — routed to `frontend-engineer` like other visual
  defects.
- The fast path is unchanged and remains the escape hatch for trivial
  work.
