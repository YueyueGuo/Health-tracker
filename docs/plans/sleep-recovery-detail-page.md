# Sleep & Recovery Detail Page

## 1. Summary
Finish the Sleep & Recovery detail page so it lives inside the modern PWA shell (sticky header + bottom nav, no left sidebar) and serves as the dedicated landing surface for a side-by-side WHOOP vs Eight Sleep comparison powered by `SleepRecoveryDetailsCard`. The home page's Morning Status card (sleep + recovery circles) becomes a tap target that jumps straight to this page. The work is fully contained in the frontend — backend already returns per-source data via `/sleep?source=` and `/sleep/latest?source=`. Apple Health is explicitly excluded; this page stays a two-column comparison.

## 2. Affected files

### Backend
| Path | Change |
|------|--------|
| (none expected) | Per-source data already exposed by `backend/routers/sleep.py:23-44, 93-123` (`/sleep`, `/sleep/latest?source=`) and `backend/routers/recovery.py:17-36` (`/recovery?days&as_of`). No new endpoints needed. |

### Frontend
| Path | Change |
|------|--------|
| `frontend/src/App.tsx` | Move `/sleep` (and likely `/recovery`) out of `<Layout>` and into `<AppShell>` so the page uses the modern bottom-nav shell rather than the legacy left sidebar. Optionally introduce a new route `/sleep-recovery` (alias) if we want a separate landing slug; otherwise keep `/sleep` as the canonical path. |
| `frontend/src/components/Sleep.tsx` | Replace contents: remove the `Layout`-era `page-header` block, top trend selector, score chart, stages chart, and "Recent nights" table that duplicate the detail card. Keep only the page-level concerns: data fetching for `latestWhoop`, `latestEight`, recovery; pairing logic (`mergeSleepSessions`, `resolveSleepPairForCard`, `pickRecoveryForSleeps`); render `<SleepRecoveryDetailsCard>` and any new trend cards in `AppShell`-compatible styling. Drop unused recharts imports. |
| `frontend/src/components/sleep/SleepRecoveryDetailsCard.tsx` | Minor: the in-component sticky back-button header currently does `navigate(-1)` — when entered from the home card tap-through, `-1` works. Keep but verify the gradient/sticky offset matches `HomeLayout`'s `sticky top-0` pattern. No structural rewrite. |
| `frontend/src/components/dashboard/MorningStatusCard.tsx` | Wrap the existing `<Card>` body in a `<button>` / `role="button"` link that navigates to `/sleep` on click. Preserve keyboard activation (Enter/Space), `aria-label`, and the existing visuals. The two circles, HRV/RHR row, and stages row all become part of the click target. |
| `frontend/src/components/RecoveryPanel.tsx` *(optional follow-up)* | If `/recovery` also moves out of `Layout`, restyle its `page-header`, `filter-bar`, `metric-card` shells into `Card`-based equivalents so the legacy CSS doesn't leak. Out-of-scope if we keep `/recovery` under `Layout` for now — call out in Risks. |
| `frontend/src/components/Layout.tsx` | After removing `/sleep` (and possibly `/recovery`) from the sidebar route group, drop the now-orphaned `Sleep` / `Recovery` nav entries from `navItems` to avoid 404-looking entries. **Do not delete Layout.tsx** — it still hosts `/ask` and `/settings`. |
| `frontend/src/components/Dashboard.test.tsx` | Update mock to assert the new clickable Morning Status card navigates to `/sleep` (or extract to `MorningStatusCard.test.tsx`). |
| `frontend/src/components/sleep/SleepRecoveryDetailsCard.test.tsx` *(new)* | Render-smoke test: passes paired whoop/eight rows + recovery → renders both column labels, the score circles, and the diff rows. |
| `frontend/src/components/Sleep.test.tsx` *(new)* | Mock `useApi` and assert the page renders within `AppShell` shape (no `app-layout`/`sidebar`) and shows the detail card. |

## 3. Backend tasks
**None.** `backend/routers/sleep.py:93-123` already supports `?source=whoop` and `?source=eight_sleep` for `/sleep/latest`, and the list endpoint accepts `?source=`. `_sleep_dict` already projects all stage/HRV/respiratory/temp fields the card consumes. `backend/routers/recovery.py:17-36` returns the WHOOP recovery row the card cross-fills with. Call out in PR description that backend was verified-only.

## 4. External integration
**Empty.** No new external APIs; data already flows from WHOOP and Eight Sleep clients into existing tables.

## 5. Frontend tasks
Ordered so a single frontend-engineer agent can execute end-to-end:

1. **Route move.** In `frontend/src/App.tsx`, move the `<Route path="/sleep" …>` line from the `<Layout>` group into the `<AppShell>` group. Decide whether `/recovery` moves too (recommended yes for consistency; if not, leave for follow-up). Confirm with `npm run typecheck`.
2. **Strip legacy Sleep wrapper.** In `frontend/src/components/Sleep.tsx`:
   - Remove the empty-state block that uses `page-header` (lines ~83–95).
   - Decide: collapse the page down to *only* the `SleepRecoveryDetailsCard` plus the trend selector + score/stages charts + recent-nights table, all wrapped in the standard `space-y-4` `AppShell` content area. Or — preferred — move charts/table to a follow-up and ship a tight detail page that is just the card + a small "Recent nights" mini-list using existing `Card` components.
   - Remove unused imports (`useState`, `LineChart`, `BarChart`, `useApi(fetchSleepTrends)`) if the trend section is dropped from this PR.
3. **Detail-card header alignment.** In `SleepRecoveryDetailsCard.tsx`, confirm the sticky header sits flush under `AppShell`'s outer container (no double sticky w/ HomeLayout's header — `/sleep` no longer renders `HomeLayout`). Adjust `-mx-4 px-4 sm:mx-0 sm:px-0` offsets if needed to match `AppShell`'s padding.
4. **Home-page click-through.** In `frontend/src/components/dashboard/MorningStatusCard.tsx`:
   - Import `useNavigate` from `react-router-dom`.
   - Wrap the entire `<Card>` body in a `button` (or render the `Card` as `<button>`) with `onClick={() => navigate("/sleep")}`, `aria-label="Open Sleep & Recovery details"`, and `cursor-pointer` / focus-visible styles.
   - Make sure nested interactive elements are absent (the card has none today), so no nested-button issue.
5. **Sidebar cleanup.** In `frontend/src/components/Layout.tsx`, remove the `{ to: "/sleep", label: "Sleep" }` (and `/recovery` if moved) entries from `navItems` so the sidebar that still hosts `/ask` and `/settings` doesn't dangle broken links.
6. **Smoke tests** (see section 8).
7. **Visual check** of mobile + desktop widths against the existing AppShell pages (`/record`, `/history`).

## 6. Tests
Listed by file:
- `frontend/src/components/sleep/SleepRecoveryDetailsCard.test.tsx` *(new)* — render with mocked `whoopSleep`, `eightSleep`, `recovery` props; assert: both source labels render, both score circles render, diff row renders (e.g., HRV delta string), stage bars render when stages > 0. Use `@vitest-environment jsdom` + `MemoryRouter` since the card calls `useNavigate`.
- `frontend/src/components/Sleep.test.tsx` *(new)* — mock `useApi` for `fetchLatestSleepBySource("whoop")`, `fetchLatestSleepBySource("eight_sleep")`, `fetchSleepSessions`, `fetchRecovery`. Assert the detail card is in the document; assert no `.app-layout` or `.sidebar` class appears in the rendered tree.
- `frontend/src/components/Dashboard.test.tsx` — keep existing assertions; add one for clickability if test continues to mock `MorningStatusCard`, otherwise leave as-is.
- `frontend/src/components/dashboard/MorningStatusCard.test.tsx` *(new, optional)* — render inside `MemoryRouter`, click the card, assert `navigate` was called with `/sleep`. Use `vi.fn()` injected via `useNavigate` mock.
- **Backend**: none. Confirm by running existing `tests/test_routers/test_sleep.py` and `tests/test_routers/test_recovery.py` unchanged.

## 7. Migration tasks
**None.** No schema changes. Confirm `alembic heads` matches the value in `AGENTS.md` (`c2f7a4e91b85` as of last verification) before merging, but no new revision needed.

## 8. Parallelism plan
```
phase 1 (sequential, single agent):
  - feature-planner (this doc — done)

phase 2 (parallel):
  - frontend-engineer  → route move + Sleep.tsx rewrite + MorningStatusCard
                         click-through + Layout.tsx sidebar cleanup
  - (no backend-engineer needed — backend confirmed supports per-source data)

phase 3 (sequential):
  - test-runner   → vitest (frontend), npm run typecheck, npm run build,
                    pytest (sanity)
  - code-reviewer
```
Note: only one frontend agent needed; do not spawn a backend-engineer for this PR. The integration-researcher is also unnecessary (no external API touched).

## 9. Open questions for integration-researcher
**None.** No external APIs in scope. The only question worth flagging to the user (not the researcher) is in Risks below.

## 10. Risks & rollback
- **Risk — `/recovery` left in legacy shell.** If we move only `/sleep` out of `<Layout>` but leave `/recovery` behind, the sidebar `Layout` will still ship `/ask` and `/settings`, and a stale "Recovery" nav entry would either need to stay (pointing into legacy `RecoveryPanel` styling) or be deleted (then there is no link to `/recovery` from the new shell). **Mitigation**: in this PR, drop both `/sleep` and `/recovery` nav links from `Layout`, but only move `/sleep`'s route definition. The user can still reach `/recovery` via deep link; full restyle is a follow-up tracked separately.
- **Risk — sticky header collision.** `SleepRecoveryDetailsCard` has its own sticky back-button header (`SleepRecoveryDetailsCard.tsx:133`). `AppShell` does not provide an outer sticky header, so this should be fine — but verify on mobile that the safe-area top inset doesn't double-pad.
- **Risk — Apple Health branch conflict.** A parallel branch is adding Apple Health. To stay isolated:
  - Do not touch `backend/clients/`, `backend/routers/`, or `backend/models/`.
  - Do not import from any `appleHealth*` API client (none should exist on this branch).
  - Do not add a third comparison column or any source-agnostic abstraction that would invite Apple Health joining; the card remains hard-coded `whoop` vs `eight_sleep`.
- **Risk — `navigate(-1)` from a deep link.** If the user lands on `/sleep` from a notification/PWA shortcut, the back button has nowhere to go. **Mitigation**: keep `navigate(-1)` but consider falling back to `navigate("/")` if `window.history.length <= 1`. Small extra hardening; flag in PR for reviewer.
- **Rollback plan.** Pure-frontend PR with no migration. Rollback = revert the PR. No DB state, no scheduler effect. CI must pass `ruff`, `pytest`, `npm run typecheck`, `npm run build`.

---

**Relevant file paths**
- `/home/user/Health-tracker/frontend/src/App.tsx`
- `/home/user/Health-tracker/frontend/src/components/Sleep.tsx`
- `/home/user/Health-tracker/frontend/src/components/sleep/SleepRecoveryDetailsCard.tsx`
- `/home/user/Health-tracker/frontend/src/components/dashboard/MorningStatusCard.tsx`
- `/home/user/Health-tracker/frontend/src/components/Dashboard.tsx`
- `/home/user/Health-tracker/frontend/src/components/Dashboard.test.tsx`
- `/home/user/Health-tracker/frontend/src/components/Layout.tsx`
- `/home/user/Health-tracker/frontend/src/components/AppShell.tsx`
- `/home/user/Health-tracker/frontend/src/components/HomeLayout.tsx`
- `/home/user/Health-tracker/frontend/src/components/dashboard/BottomNav.tsx`
- `/home/user/Health-tracker/frontend/src/components/RecoveryPanel.tsx`
- `/home/user/Health-tracker/frontend/src/api/sleep.ts`
- `/home/user/Health-tracker/frontend/src/api/recovery.ts`
- `/home/user/Health-tracker/backend/routers/sleep.py`
- `/home/user/Health-tracker/backend/routers/recovery.py`
- `/home/user/Health-tracker/frontend/src/styles/globals.css` (legacy `page-header`, `metric-card`, `filter-bar` classes that the new shell replaces with `Card`)
