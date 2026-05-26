# Settings page redesign + units cascade

## 1. Feature summary

Rebuild the Settings page (reached from Profile's gear icon) to match the
public mockup in `YueyueGuo/health-tracker-frontend`'s `SettingsPage.tsx`:
a dark-themed AppShell page with four cards — Account (name / email / DOB),
Preferences (units toggle), Gear (shoes entry), and Data Sources (live
connection health). Add `dateOfBirth` to the profile schema, drop the
indigo legacy sidebar from this route, and complete the cascade of the
existing `useUnits` selection through the few remaining hardcoded `lb` /
`kg` weight suffixes so that toggling Imperial/Metric updates distance,
speed, and weight everywhere.

## 2. Affected surfaces

| Surface | Change | Files |
|---|---|---|
| `frontend/src/pages/Settings.tsx` | Full rewrite to mockup layout under AppShell | `frontend/src/pages/Settings.tsx` |
| `frontend/src/components/settings/` | New per-card components | `AccountCard.tsx` (new), `PreferencesCard.tsx` (new), `GearCard.tsx` (new), `AdvancedSection.tsx` (new) |
| `frontend/src/components/settings/` | Reuse / re-home existing sections | `GoalsSection.tsx`, `LocationSettingsSection.tsx`, `SyncSection.tsx`, `ShoesSettingsCard.tsx` (move under Advanced expander, no rewrite) |
| `frontend/src/components/profile/` | Move DataSourcesCard usage from Profile to Settings | `DataSourcesCard.tsx` (no change), `pages/Profile.tsx` (remove the card) |
| `frontend/src/App.tsx` | Move `/settings` route from `<Layout>` to `<AppShell>` | `frontend/src/App.tsx:51-54` |
| `frontend/src/components/Layout.tsx` | Remove the in-sidebar units toggle (now lives in Settings) | `frontend/src/components/Layout.tsx:30-49` |
| `frontend/src/hooks/useUnits.tsx` | Add a `formatWeight(valueLb, opts)` helper alongside the existing distance/speed formatters | `frontend/src/hooks/useUnits.tsx` |
| `frontend/src/hooks/useProfilePreferences.ts` | Add `dateOfBirth` to type / defaults / parser | `frontend/src/hooks/useProfilePreferences.ts` |
| `frontend/src/components/profile/PhysiologyVitalsCard.tsx` | Replace hardcoded `lb` weight suffix with `useUnits` | `PhysiologyVitalsCard.tsx:19` |
| `frontend/src/components/record/usePriorPerformance.ts` | Replace hardcoded `kg` weight suffix with `useUnits` | `usePriorPerformance.ts:47` |
| `backend/routers/profile.py` | Add `dateOfBirth` to `ProfilePayload` / `ProfilePatch` / `_apply_patch` / `PROFILE_DEFAULTS`; validate `""` or `YYYY-MM-DD` | `backend/routers/profile.py` |
| `tests/` | Update + add unit/component tests | `frontend/src/pages/Settings.test.tsx`, `Profile.test.tsx`, `tests/test_routers/test_profile.py` |

## 3. Data model

- **No new tables, no new columns, no migration.** `user_profile.payload`
  is a JSON column (`backend/models/user_profile.py`); adding
  `dateOfBirth` is purely a Pydantic schema extension.
- Field added to the JSON payload: `dateOfBirth: str` (camelCase alias on
  the wire). Empty string `""` means "not set". Otherwise required to
  match `^\d{4}-\d{2}-\d{2}$` (validate via
  `datetime.date.fromisoformat`; reject malformed dates with 422).
- No backfill needed — existing payloads without the key parse with
  default `""`.
- `vitals.weight` storage: unchanged. It remains a free-text string in
  whatever unit the user typed it in originally. **Display** unit comes
  from `useUnits`; we do not auto-convert the stored value when the user
  flips the toggle. (Risk noted in §10; cleaner normalization to kg is
  deferred.)

## 4. External integration

N/A — no third-party APIs touched. The Data Sources card already calls
existing `/sync/...` and per-integration status endpoints via
`DataSourcesCard.tsx`; we are only relocating it.

## 5. Backend tasks

1. `backend/routers/profile.py`: add
   `date_of_birth: str = Field("", alias="dateOfBirth")` to
   `ProfilePayload` and `ProfilePatch`. Add a field validator that
   accepts `""` or `YYYY-MM-DD` (parse via
   `datetime.date.fromisoformat`); reject anything else.
2. `backend/routers/profile.py`: extend `PROFILE_DEFAULTS` with
   `"dateOfBirth": ""`.
3. `backend/routers/profile.py`: extend `_apply_patch` to merge
   `dateOfBirth` like the other top-level string fields.
4. Confirm `model_config` already has `populate_by_name=True` and
   `by_alias` serialization so the field round-trips as `dateOfBirth` to
   the FE. If not, add it.
5. (Sanity) verify the JSON column read path tolerates missing
   `dateOfBirth` on existing rows — defaults must fill in.

## 6. Frontend tasks

1. **Hook updates** — `frontend/src/hooks/useProfilePreferences.ts`:
   - Add `dateOfBirth: string` to `ProfilePreferences`.
   - Add `dateOfBirth: ""` to `DEFAULT_PROFILE_PREFERENCES`.
   - Update `parseProfilePreferences` to read `dateOfBirth` defensively
     (default `""`).
2. **Units helper** — `frontend/src/hooks/useUnits.tsx`:
   - Add `formatWeight(valueLb: number, opts?: { digits?: number; suffix?: boolean })`
     that converts to kg when `units === "metric"` and returns a
     formatted string. Export from the same hook surface used by
     `formatDistance` / `formatPace`.
3. **New Settings page** — `frontend/src/pages/Settings.tsx`:
   - Replace existing body. Render: sticky header (back arrow →
     `navigate(-1)` + h1 "Settings"), then 4 cards: `<AccountCard />`,
     `<PreferencesCard />`, `<GearCard />`, `<DataSourcesCard />`, then
     `<AdvancedSection />`.
   - Wrap in the standard AppShell main container (no `<Layout>`).
4. **AccountCard** — `frontend/src/components/settings/AccountCard.tsx`:
   - Editable rows for `displayName`, `email`, and `dateOfBirth` (DOB
     uses `<input type="date">`, allow blank).
   - Reuse the same persistence pattern as `ProfileHeader` (PATCH via
     `useProfilePreferences`).
   - Display rendering of DOB: format via
     `Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" })`
     when present; show "Not set" placeholder when empty.
5. **PreferencesCard** —
   `frontend/src/components/settings/PreferencesCard.tsx`:
   - Segmented Imperial / Metric toggle bound to `useUnits`. No
     notifications toggle (deferred).
6. **GearCard** — `frontend/src/components/settings/GearCard.tsx`:
   - Single row labeled "Shoes" with summary count (reuse the count
     computation already inside `ShoesSettingsCard`) and right-chevron
     link to `/shoes`.
7. **AdvancedSection** —
   `frontend/src/components/settings/AdvancedSection.tsx`:
   - Collapsible (closed by default). Contains existing
     `<GoalsSection />`, `<LocationSettingsSection />`,
     `<SyncSection />` unchanged.
8. **Profile cleanup** — `frontend/src/pages/Profile.tsx`: remove the
   `<DataSourcesCard />` render (and the corresponding test assertion).
9. **Routing** — `frontend/src/App.tsx`: move the `/settings` `<Route>`
   out of the `<Layout>` group and into the `<AppShell>` group
   (alongside `/profile`, `/record`, etc.).
10. **Legacy layout** — `frontend/src/components/Layout.tsx`: delete the
    units toggle block (lines ~30-49). `useUnits` is shared context and
    the Settings page is now its single source of truth.
11. **Unit cascade fixes**:
    - `frontend/src/components/profile/PhysiologyVitalsCard.tsx:19` —
      replace hardcoded `suffix: "lb"` with the active unit from
      `useUnits`.
    - `frontend/src/components/record/usePriorPerformance.ts:47` — same
      treatment for the hardcoded `kg` suffix in the prior-performance
      hint.
    - Repo-wide grep checklist (to be run by the engineer):
      `"\blb\b"`, `"\bkg\b"`, `"\bmph\b"`, `"\bmi\b"`, `"\bkm\b"` under
      `frontend/src/`, excluding strings already inside a `useUnits`
      branch. Convert any straggler labels to the hook.
12. **Color audit**: confirm new Settings markup uses `bg-dashboard` /
    `brand-green` Tailwind tokens (matches Profile/Dashboard) — no
    inline indigo or `var(--accent)` references on this page.

## 7. Migration tasks

**None.** `dateOfBirth` lives inside the existing `user_profile.payload`
JSON column. No Alembic revision, no schema changes.

**Risk: trivial** — no migration produced at all in this plan.

## 8. Tests to add

- `frontend/src/pages/Settings.test.tsx` (rewrite):
  - Renders the four cards under AppShell (assert headings: Account,
    Preferences, Gear, Data Sources).
  - Editing name / email / DOB calls the `useProfilePreferences` patch
    with the correct camelCase payload.
  - Toggling Preferences → Metric updates `localStorage["ht.units"]` to
    `"metric"` and the next render of a downstream consumer reflects kg.
  - DOB input accepts `YYYY-MM-DD` and renders the formatted "Oct 12,
    1993" display string.
  - Gear row links to `/shoes`.
  - Advanced section is collapsed by default; expanding reveals
    `GoalsSection` / `LocationSettingsSection` / `SyncSection`.
- `frontend/src/pages/Profile.test.tsx`:
  - Assert `DataSourcesCard` is **not** rendered on Profile (regression
    guard).
- `frontend/src/components/profile/PhysiologyVitalsCard.test.tsx`
  (new or extend):
  - Mounts under `UnitsProvider` set to metric → suffix renders as `kg`.
    Imperial → `lb`.
- `tests/test_routers/test_profile.py`:
  - GET returns `dateOfBirth: ""` for a fresh profile.
  - PATCH `{"dateOfBirth": "1993-10-12"}` persists and round-trips.
  - PATCH `{"dateOfBirth": "not-a-date"}` returns 422.
  - PATCH `{"dateOfBirth": ""}` is accepted (clear).

## 9. Parallelism plan

```
phase 1 (parallel):
  - backend-engineer  → ProfilePayload/Patch + validator + defaults
                        + test_profile.py
  - frontend-engineer → useProfilePreferences extension, new Settings
                        page + subcomponents, DataSourcesCard move,
                        Layout toggle removal, App.tsx route move,
                        unit-cascade fixes, useUnits.formatWeight,
                        FE tests

phase 2 (sequential):
  - test-runner       → pytest + npm run typecheck + npm run build
                        + vitest
  - code-reviewer     → diff review against this plan
  - pr-author         → open PR against main
```

`db-migrator`, `integration-researcher`, and `migration-safety-checker`
are all **skipped** (no migration, no external integration, no
production data touched).

## 10. Risks and rollback

- **Highest risk**: the units toggle change in `Layout.tsx` is a shared
  chrome edit. If the new Settings toggle ships broken, users on `/ask`
  would temporarily have no way to flip units. Mitigation: land the new
  Settings toggle in the same PR, and gate Layout removal behind a
  passing Settings test.
- **Vitals weight unit drift** (called out in §3): existing string
  weight values are unit-tagless. Flipping the display unit will
  mis-label legacy values. Mitigation for now: an inline "Edit to update
  unit" hint near the weight field. Proper fix (normalize storage to kg)
  is a follow-up plan.
- **DOB schema field**: even though there's no migration, deployed JSON
  rows without the key must default to `""`. Backend defaulting logic is
  the only safeguard — covered by the new round-trip test.
- **Indigo holdouts**: `globals.css` still defines `--accent: #6366f1`
  for other Layout consumers. We are not removing the token — only
  ensuring the new Settings page never references it.
- **Rollback plan**: pure FE + JSON payload change → revert the PR. No
  DB migration, so rollback is mechanical (`git revert`); existing rows
  are forward-compatible with the old schema.
