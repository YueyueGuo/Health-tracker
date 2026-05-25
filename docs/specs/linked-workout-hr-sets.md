# Spec: Link manual strength sessions to device workouts with HR-aligned analysis

## Problem
When the project owner logs a manual strength workout (sets, reps,
weight) on the dashboard, they often also wore a watch that
recorded the same session as a separate device workout with a
heart-rate stream. Today there's no UI to connect those two records,
so the user can't see "what was my HR during my 4th squat set?"
even though both data points exist. The infrastructure to align HR
to sets already exists in the backend (`strength_hr.py`,
`session_summary` returns merged `avg_hr`/`max_hr` per set when a
Strava activity is linked) but it can only be triggered by passing
`activity_id` in the initial bulk-insert payload, which the current
Record UI hard-codes to `null`. On top of that, many sessions are
logged in bulk after the fact and have no per-set `performed_at`
timestamps, which today means per-set HR is empty even when a
workout is linked.

## Outcome
After a strength session, the owner can: (1) pick a device-recorded
workout from a list of candidates near that day and link it to the
manual session in two taps; (2) immediately see each set annotated
with the working HR and a session-wide HR curve — even when the
sets were logged without per-set timestamps, because v1 derives set
boundaries from the HR stream itself.

## User story
As the project owner (single user of this PWA), I want to link a
manual strength session to the device workout that recorded the
same training block, so that I can see per-set HR and understand
how my body responded to the lifts I actually did.

## In scope
- A "Link device workout" affordance on the strength session detail
  view that surfaces candidate device workouts overlapping the
  session date (default: same day, plus a day before/after to
  catch tz / late-night cases).
- Showing source labels for each candidate (Strava / Apple Health),
  start time, duration, sport type, avg/max HR — enough to
  disambiguate "garage lift" from "afternoon run".
- Persisting the chosen link so subsequent loads of the session
  show HR-annotated sets and the session-wide HR curve.
- Allowing the user to unlink / change the linked workout after
  the fact (mistakes happen, especially when two workouts overlap).
- **Auto-segmenting sets from the HR stream**: once a workout is
  linked, the backend infers per-set HR windows from peaks/valleys
  in the smoothed HR curve rather than depending on each set's
  `performed_at`. The set count logged on the strength session is
  used as a target for the segmenter.
- Linking is **1:1**: one manual session links to exactly one
  device workout, and a given device workout can be linked to at
  most one manual session.
- Sources supported in v1: **Strava and Apple Health** only.

## Out of scope (for this iteration)
- **Whoop as a link target.** Whoop has no per-set HR stream that
  would benefit from auto-segmentation, and adding it would force a
  generalized "linked workout" schema before Apple Health has even
  proven out. Revisit if/when per-set alignment from Apple Health
  is shown to be useful.
- Linking from any source other than the **already-ingested**
  device workout records. No new device API integration.
- Auto-suggesting / auto-creating the link without a confirmation
  tap. The owner stays in the loop for v1 (false positives are
  worse than one extra tap).
- LLM narrative generation on the linked session. v1 ships the
  merged set+HR view only; v2 will feed the same payload into the
  existing insights service. No "Generate analysis" button in v1.
- Editing past sets' `performed_at` from the link flow. With
  auto-segmentation, this is no longer needed for HR alignment, so
  v1 simply doesn't expose set-timestamp editing.
- Manual override of segment boundaries on the HR curve (drag to
  reshape segments). Deferred to v2 if auto-segmentation proves
  unreliable in practice.
- Multi-session-to-one-device-workout linking and one-session-to-
  many-device-workouts. The cardinality is strictly 1:1.
- Cross-source linking of device workouts to each other (Apple
  Health ↔ Strava). That's a separate dedup problem.
- Sharing / export of the linked-and-analyzed session.
- A separate "linked sessions" index page. Discovery stays on the
  existing session detail view.
- Linking entry points other than the session detail view (no
  "link right after logging" affordance on the Record page in v1).

## Acceptance criteria
- [ ] On a strength session detail view with no linked device
      workout, the user sees a "Link device workout" affordance.
- [ ] Tapping it opens a picker listing candidate device workouts
      (Strava and Apple Health) from the same day (and ±1 day)
      ordered by start time, with source, sport, duration, avg HR
      visible per row.
- [ ] Picking a candidate persists the link and the view re-renders
      with a session-wide HR curve and per-set `avg_hr`/`max_hr`
      columns derived from auto-segmentation of the HR stream.
- [ ] Auto-segmentation works on sessions whose sets have **no**
      `performed_at` timestamps — the dependency on per-set
      timestamps for HR alignment is removed in v1.
- [ ] On a session that already has a linked workout, the same
      area shows the linked workout's summary plus an "Unlink" or
      "Change" action.
- [ ] When the linked workout's HR streams aren't cached yet
      (Strava lazy stream), linking triggers an on-demand fetch and
      the view shows a clear loading state until the stream
      resolves, then renders the curve and per-set HR.
- [ ] When the on-demand stream fetch fails (rate limit, token
      expired, no stream available for that activity), the view
      shows the link + summary with an explicit error state, not a
      blank panel, and offers a retry.
- [ ] When no candidate device workouts exist for the date range,
      the picker shows an explicit empty state explaining why
      (not just an empty list).
- [ ] A linked session round-trips through reload — link state is
      visible on the session list view (e.g. a small indicator
      that this session is HR-linked).
- [ ] When the auto-segmenter finds fewer segments than the logged
      set count, the per-set table shows HR for as many sets as
      were detected and renders "—" for the remainder, with a
      tooltip ("auto-segmentation found N of M sets"). The
      session-wide curve still renders.

## Edge cases
- **No per-set timestamps**: auto-segmentation handles this — show
  curve and per-set HR derived from inferred segments.
- **Streams not cached** (Strava on-demand stream API): trigger
  fetch on link; show loading state; on success render normally;
  on failure show a retry-able error.
- **Multiple overlapping candidates** (Strava + Apple Health both
  recorded the same lift): both appear in the picker; user
  chooses one. We do not auto-pick.
- **Candidate workout spans midnight**: the ±1 day window covers
  this; the picker shows the actual start time.
- **User unlinks then re-links to a different workout**: the HR
  curve and per-set HR re-compute from the new workout's streams.
- **Linked workout deleted upstream / row purged**: the manual
  session shows an "originally linked workout is no longer
  available" state with an option to clear or re-link. Apple
  Health link cleanup behavior is left to the planner.
- **Apple Health workout has avg/max HR but no time series**: the
  link saves and the session-level HR summary shows, but the curve
  and auto-segmented per-set HR are unavailable; the UI surfaces
  this explicitly.
- **Auto-segmenter finds fewer segments than logged sets**: show
  HR on the N detected sets in logged order; remaining sets render
  "—" with a tooltip explaining "auto-segmentation found N of M
  sets". The session-wide curve and summary still display.
- **Auto-segmenter finds more segments than logged sets**: extra
  segments are dropped from the per-set table; the curve still
  shows all detected peaks.
- **Device workout is very short or has flat HR** (e.g. accidental
  recording): segmenter may return zero usable segments; the link
  is preserved but per-set HR shows empty with a "couldn't detect
  set boundaries from HR" explanation.

## UX sketch
**Location**: extend the existing strength session detail view
that's already reached via the History / session-list flow. The
Record page is **not** an entry point in v1.

Top-to-bottom on the session detail page:
1. Existing header (date, total volume, exercise count).
2. **New "Device workout" panel**, immediately under the header:
   - Unlinked state: "No device workout linked" + `[Link…]` button.
   - Linked state: source badge ("Strava" / "Apple Health"),
     workout name/sport, start time, duration, avg HR, max HR.
     Trailing `[Change]` and `[Unlink]` controls.
   - Loading state (just-linked, streams fetching): spinner +
     "Loading heart-rate stream…".
   - Error state (fetch failed / stream unavailable): summary +
     short error + `[Retry]`.
3. Existing per-exercise breakdown — now with `Avg HR` / `Max HR`
   columns on each set row populated from auto-segmented windows.
   Sets that fall outside any detected segment show "—" with a
   tooltip ("auto-segmentation found N of M sets").
4. Session-wide HR curve under the per-exercise breakdown, with
   detected segment boundaries visually marked on the curve so the
   user can sanity-check the segmentation.

**Linking modal/sheet**: a list of candidate rows. Each row shows
source badge, sport, start time (local), duration, avg/max HR, and
distance if relevant. Tap a row → confirms and closes → view
re-renders into the loading state, then the linked state.

Session list / history view gets a small icon indicator next to
sessions that have a linked device workout, so the user can spot
which sessions are HR-enriched.

## Data needs
**Already in DB** (no new ingestion needed for v1, assuming the
device workout was synced as usual):
- `strength_sets.activity_id` — already FKs to Strava `activities`.
  Used today; the missing piece is a UI to set it post-hoc rather
  than only at insert time.
- `activities` + `activity_streams` (time, heartrate) — read by
  `strength_hr.attach_hr_to_sets` and will be the input to the
  auto-segmenter.
- `workouts` (Apple Health, joined-table on `health_data_points`)
  — has avg/max HR and duration. No HR time series by default in
  this repo; sessions linked to Apple Health get summary-only HR
  unless / until streams are present.
- `strength_sessions` / `strength_sets` set counts — used by the
  auto-segmenter as a target segment count.

**Needs new ingestion**: none expected for v1. If Apple Health HR
time series become available later, the segmenter can be reused.

**Derived / computed**:
- Candidate ranking for the picker (same-day, then ±1 day, sorted
  by start time). Trivial; planner picks where to compute.
- **Auto-segmentation algorithm**: takes a smoothed HR stream and
  a target set count, returns segment windows for each set. This
  is a research problem — see Dependencies and risks.
- Per-set `avg_hr` / `max_hr` derived from those windows, plus a
  flag indicating segmentation confidence / mismatch with the
  logged set count.

## Dependencies and risks
- **Auto-segmentation from HR peaks is a research problem.** The
  planner will need to scope:
  - Algorithm choice: e.g. peak/valley detection on a smoothed HR
    trace; set-count-aware partitioning that snaps to the logged
    number of sets; possibly hybrid use of the device workout's
    timestamps (start of activity, breaks if any) as priors.
  - Failure modes: flat HR, noisy HR, very long rest periods that
    look like the end of the workout, segmenter finding too few or
    too many candidates.
  - Confidence signal returned to the UI so the front-end can
    decide what to show per the Segment UX follow-up.
  - Whether the segmenter runs synchronously on link (simpler) or
    is cached on the session row (faster on reload).
- **Strava streams are lazy**: linking triggers an on-demand stream
  fetch. The planner must decide where this is invoked from and
  how it surfaces back-pressure (rate limits, partial failure).
- **Apple Health lacks HR time series in this repo today**. Linking
  to an Apple Health workout gets you session-level HR only; the
  curve and auto-segmentation degrade to "summary only" with a
  clear UI affordance.
- **Existing strength session detail endpoint** already returns
  HR-merged data when `activity_id` is set, but its per-set merge
  is timestamp-driven (`_slice_hr_for_set`). v1 changes the
  per-set merge path to be segmentation-driven; the planner needs
  to be explicit about whether this replaces or coexists with the
  timestamp model.
- **Schema for Apple Health link target**: today `strength_sets`
  has `activity_id` FK to Strava only. Linking to Apple Health
  needs a generic link representation (source + external id) on
  the session, not on each set. This is a non-trivial migration;
  flag for the planner.
- **No new external API integration** is required.
- **v2 future work** (not in this spec): feed the merged set + HR
  + segmentation payload into `backend/services/insights.py` to
  produce an LLM narrative on the linked session. Out of scope
  here; documented so the planner doesn't paint v1 into a corner.

## Success metric
The owner stops needing to mentally cross-reference their watch
app and the dashboard after a lift. Concretely: at least one of
the next 5 lifting sessions logged in the app gets manually linked
and looked at, and the owner reports the per-set HR (especially on
sessions logged in bulk without timestamps) actually changed how
they thought about the session. "I'll see if I keep using it" is
a valid bar.

## Open questions
None. All decisions from the /spec round-trip are encoded above.
