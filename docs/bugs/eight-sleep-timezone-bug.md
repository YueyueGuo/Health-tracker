# Eight Sleep Timezone Bug — Diagnosis

## 1. Symptom

User in US Eastern (EDT, UTC−4). On the Sleep & Recovery card for Sat May 16,
the two sources show wildly different bed/wake clock times for the same night:

- **WHOOP**: 11:18 PM → 7:17 AM EDT (correct — matches the user's real sleep).
- **Eight Sleep**: 7:17 PM → 3:21 AM (4 hours earlier than reality).

The 4-hour offset exactly matches the user's UTC offset, indicating an
`astimezone` is applied one too many times somewhere between Eight Sleep's
UTC API response, the DB, and the React `toLocaleTimeString` call.

## 2. Reproduction (read-only)

Add a unit test against `_extract_fields` + `_attach_utc_to_sleep_times` (the
exact pair `_sync_window` calls in sequence at
`backend/services/eight_sleep_sync.py:118`) and assert what the JS frontend
would see:

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from backend.services.eight_sleep_sync import _extract_fields, _attach_utc_to_sleep_times

# Real bed time: 23:18 EDT on 2026-05-16 == 03:18Z on 2026-05-17
trend = {
    "day": "2026-05-17",
    "sleepStart": "2026-05-17T03:18:00Z",
    "sleepEnd":   "2026-05-17T11:17:00Z",
    "sleepDuration": 7 * 3600 + 59 * 60,
    "presenceDuration": 7 * 3600 + 59 * 60,
    "mainSessionId": "abc",
}
interval = {"timezone": "America/New_York", "ts": "2026-05-17T03:18:00Z", "stages": [], "timeseries": {}}

fields = _attach_utc_to_sleep_times(_extract_fields(trend, interval))
bed = fields["bed_time"]                       # currently datetime(2026-05-16 23:18, tzinfo=UTC)
seen_by_frontend = bed.astimezone(ZoneInfo("America/New_York"))
assert seen_by_frontend.hour == 23             # FAILS today (returns 19)
```

The frontend serializer (`backend/routers/sleep.py:132`) calls `.isoformat()`
on the tz-aware value, producing `"2026-05-16T23:18:00+00:00"`; the React side
(`formatClockTime` at `frontend/src/components/sleep/SleepRecoveryDetailsCard.tsx:687-695`)
constructs `new Date(iso)` and calls `.toLocaleTimeString`, which honours the
`+00:00` and subtracts another 4 hours → 19:18 (7:18 PM). That's exactly what
the user observed.

## 3. Root cause (H1, highest confidence)

`_attach_utc_to_sleep_times` slaps `tzinfo=UTC` on values that are actually
naive *local* wall-clock, so naive-local-EDT gets relabeled as UTC and
re-converted on display.

- `backend/services/eight_sleep_sync.py:186-204` — `_attach_utc_to_sleep_times`
  does `val.replace(tzinfo=timezone.utc)` (no `astimezone`) on the output of
  `_to_local`.
- `backend/services/eight_sleep_sync.py:582-593` — `_to_local` ends with
  `dt.astimezone(tz).replace(tzinfo=None)`, returning a **naive local
  wall-clock** datetime. So when `_attach_utc_to_sleep_times` then
  `replace(tzinfo=timezone.utc)` runs, the wall-clock numbers (e.g.
  `2026-05-16 23:18`) are mislabeled as UTC and the value Postgres stores is
  `2026-05-16T23:18:00Z` instead of `2026-05-17T03:18:00Z`.
- `backend/models/sleep.py:20-21` — `bed_time` / `wake_time` are
  `DateTime(timezone=True)` since commit `35d648f` (per
  `docs/audit-001-datetime-sweep-audit.md:65-66`).
- `backend/routers/sleep.py:132-133` — `_sleep_dict` emits
  `s.bed_time.isoformat()`, so the wrong tz is shipped to the client as
  `+00:00`.
- `frontend/src/components/sleep/SleepRecoveryDetailsCard.tsx:687-703` —
  `formatClockTime` calls `new Date(iso).toLocaleTimeString`, which honours
  the tz suffix and converts UTC → local → second 4-hour subtraction.

**This is the deferred "Follow-up #3" in `docs/audit-001-datetime-sweep-audit.md:145-157`:**

> "For Eight Sleep specifically, the values coming out of `_extract_fields`
> represent naive *local* wall-clock — yet this PR labels them as UTC. … a
> downstream consumer that does tz math on `bed_time` will read '23:00 UTC'
> when the user actually went to bed at '23:00 local', and will be off by the
> user's UTC offset."

The user is now observing that deferred regression in production.

### Why WHOOP works but Eight Sleep doesn't

WHOOP's `_parse_dt` (`backend/services/whoop_sync.py:36-53`) does
`datetime.fromisoformat(s).astimezone(timezone.utc)` — genuinely tz-aware UTC.
Stored as real UTC, then frontend converts UTC → EDT → user's actual clock
time. The Eight Sleep path strips tzinfo via `_to_local` then re-labels naive
local as UTC, producing the double subtraction.

## 4. Recommended fix (backend-only)

**Option A — make the DB hold true UTC, matching the WHOOP path.**

- `backend/services/eight_sleep_sync.py`:
  - In `_extract_fields` (around lines 281-290), do **not** call `_to_local`
    on the values written to `bed_time` / `wake_time`. Use the tz-aware UTC
    datetime that `_parse_dt` already returned.
  - Change `_attach_utc_to_sleep_times` (lines 186-204) to either a no-op or
    a defensive `astimezone(timezone.utc)` normalisation (not
    `.replace(tzinfo=...)`).
- `_index_intervals_by_date` at lines 487-499 keys off `start_ts.hour >= 18`
  to decide which night an interval belongs to. After the fix it will be
  called with **UTC** datetimes; `start_ts.hour` will be the UTC hour, not
  local. This needs to convert to local before the hour comparison, or it
  will misclassify (e.g. 23:18 EDT = 03:18 UTC, hour=3, would land on the
  wrong night).
- `backend/routers/sleep.py:132-133` is fine — `isoformat()` on a tz-aware
  UTC datetime emits the correct `+00:00`, the frontend's
  `new Date(iso).toLocaleTimeString` will then correctly produce 11:18 PM
  EDT.

**Side effect:** historical Eight Sleep rows in Postgres remain off by 4-5h
(depending on DST) until backfilled. Backfill is **out of scope** of this
bug; see §5.

### Tests required

- **New regression unit test** in `tests/test_sync/test_eight_sleep_sync.py`:
  - Build a trend dict with `sleepStart=2026-05-17T03:18:00Z`,
    `sleepEnd=2026-05-17T11:17:00Z`, `interval["timezone"]="America/New_York"`.
  - Call the post-fix pipeline.
  - Assert: `fields["bed_time"].astimezone(ZoneInfo("America/New_York")).strftime("%H:%M") == "23:18"`
    and likewise wake → `"07:17"`. On `main` today, this asserts `"19:18"`
    and fails.
- **New integration test** in `tests/test_routers/test_sleep.py`:
  - Insert a `SleepSession(source="eight_sleep", ...)` row with the *correct*
    tz-aware UTC value the new code path produces.
  - GET the sleep endpoint and assert the returned `bed_time` ISO string,
    when parsed in `America/New_York`, yields the user's expected wall-clock.
- **Existing tests to update** at `tests/test_sync/test_eight_sleep_sync.py:297-329`:
  - `test_to_local_*` and `test_extract_fields_returns_bed_time_in_local_tz`
    enshrine the buggy contract (assert that `bed_time` is the naive-local
    wall-clock datetime). Rewrite to assert tz-aware UTC.
- **Existing tests to update** at `tests/test_datetime_sweep_callsites.py:62-93`:
  - `test_attach_utc_to_sleep_times_tags_naive_in_place` asserts the exact
    buggy behaviour. Delete or rewrite.
- **Targeted test for `_index_intervals_by_date`** that a 23:18 EDT interval
  (= 03:18 UTC) still gets keyed to the correct night date (May 16).

### Migration

None required — the column type stays `DateTime(timezone=True)`; only the
*value* written changes.

## 5. Out-of-scope follow-ups

- **Backfill existing rows.** A `scripts/backfill_eight_sleep_tz.py` could
  re-fetch or simply add the per-night UTC offset to historical rows. Worth a
  dedicated follow-up issue.
- **Awake-time discrepancy (1h 44m vs 13m)** in the screenshot is unrelated
  to tz. Eight Sleep counts presence-in-bed-but-not-asleep; WHOOP counts
  in-bed disturbances. Real data-semantics difference — a UI tooltip would
  help.
- **`_resolve_tz` silent fallback** (`backend/services/eight_sleep_sync.py:570-579`)
  to env when the interval payload is missing — worth a log line.
- **Close the loop** on `docs/audit-001-datetime-sweep-audit.md` Follow-up #3
  once the fix ships.
