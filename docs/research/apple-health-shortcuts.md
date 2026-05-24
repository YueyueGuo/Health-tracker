# Apple Health via iOS Shortcuts — Integration Research

## Summary verdict

**Plain iOS Shortcuts cannot read workout records from Apple Health.** The native `Find Health Samples` action exposes scalar samples (heart rate, active energy, steps, distance, sleep analysis, etc.) but the "Workouts" container type itself is not a queryable health-sample type in that action.

There IS a native `Log Workout` action (write-only — pushes a workout into Health), a `Find Health Samples` action (read-only, scalar samples), and an `Apple Watch Workout` automation trigger (Start / End) — but the trigger does NOT pass workout details (UUID, type, energy, etc.) as magic variables.

**Net result:** the payload contract in the plan §6 is materially overstated. With plain Shortcuts the user can realistically POST:
1. A manually-selected `activity_type` (via Menu).
2. A manually-entered or trigger-derived `start`/`end`.
3. Aggregated scalars from `Find Health Samples` filtered to that window: total active energy, avg/max HR, total distance.

**No native way to obtain:** HKWorkout UUID, `WorkoutEvents` (laps), `WorkoutRoute`, per-workout sourceName/device.

**Recommendation:** either (a) accept a degraded contract with a synthesized natural key, or (b) switch to **Health Auto Export** (one-time ~$8 IAP) which gives true `id` + route series + HR series + first-class REST-export automation.

---

## Q1. Lap / event / route data

**Finding:** No. Plain iOS Shortcuts has no access to `HKWorkoutEvent` (lap/segment markers), `HKWorkoutRoute` (GPS series), or `HKWorkoutActivity` segments. The `Find Health Samples` action enumerates scalar sample types only.

**Sources:**
- Actions For Obsidian forum (czottmann): native Shortcuts does not surface workout data; Toolbox Pro is needed.
- Toolbox Pro `Get Workouts` action exists precisely because native Shortcuts cannot.
- Apple's "Intro to Find and Filter actions" lists no Find Workouts action.

**Payload-shape impact:**
- Drop `events` and `laps` arrays from the contract entirely for the plain-Shortcuts path.
- Backend falls back to server-side time-based even splits derived from `duration_s` + `distance_m`. Schema already provisions for this.

## Q2. HKWorkout UUID field name

**Finding:** Not available from plain Shortcuts at all — workouts themselves are not exposed. **Blocker** for the plan's `external_id = HK UUID` natural key.

**Proposed alternative natural key** for the plain-Shortcuts path:
```
sha256(f"{normalized_activity_type}|{start_iso_seconds}|{duration_s}")
```
Computed server-side at ingest. Deterministic for idempotent replay, collision-resistant with second-resolution start time.

## Q3. Average HR / Max HR

**Finding:** Two stages. `Find Health Samples` returns the raw HR series for the workout window; the Shortcut chains `Get Statistics → Average / Maximum` to compute scalars. ~3-4 extra Shortcut actions per stat.

## Q4. Timezone format

**Finding:** Shortcuts emits naive local time (`YYYY-MM-DD HH:MM:SS`) by default. Can be coerced to ISO 8601 with offset via `Format Date → ISO 8601`. Toolbox Pro emits UTC.

**Parser implication:**
1. Require the Shortcut recipe to emit ISO 8601 with offset (via `Format Date → ISO 8601 → Include Time = yes`).
2. If offset present → convert to UTC, strip tzinfo to match repo's naive-UTC convention.
3. If naive → assume user timezone, convert to UTC, strip tzinfo.
4. Reject anything else with 422.

## Q5. HKWorkoutActivityType string format

**Finding:** Plain Shortcuts never emits this string (workouts not exposed). Third-party paths (Toolbox Pro / HAE) surface the human-readable label (`"Running"`, `"Cycling"`), not the HK enum name (`HKWorkoutActivityTypeRunning`).

**Implication for `sport_mapping.py`:** keys must be lowercased display strings, OR the Shortcut emits a controlled-menu vocabulary (`run|ride|walk|hike|swim|strength|yoga|hiit|elliptical|row`). Strongly prefer the latter — eliminates fragility.

## Q6. Health Auto Export comparison

| Capability | Plain Shortcuts | HAE |
|---|---|---|
| Workout UUID (`id`) | No | Yes |
| Activity type label | No | Yes |
| Start / end / duration | Manually | Yes (ISO 8601 with offset) |
| Active energy, distance | Aggregable scalars only | Yes (typed) |
| Avg / max / min HR | Aggregable from samples | Yes |
| `heartRateData[]` series | Possible but slow | Yes |
| `route[]` (GPS series) | No | Yes |
| Speed, cadence, step count, flights, location | No | Yes |
| Auto "send on workout end" | Hand-rolled | First-class |
| `WorkoutEvents` lap markers | No | No (still not exposed) |

**HAE does not give lap markers either** — but it gives everything else. Server-side time-based splits remain the only practical lap source for either path.

---

## Recommended Shortcut payload contract (plain-Shortcuts path)

```json
{
  "client_request_id": "F3A2…",
  "workout": {
    "activity_type": "run",
    "start": "2026-05-24T13:14:00-04:00",
    "end":   "2026-05-24T14:02:35-04:00",
    "duration_s": 2915,
    "active_energy_kcal": 412.3,
    "distance_m": 8043.6,
    "avg_hr": 154,
    "max_hr": 178,
    "notes": "easy zone-2"
  }
}
```

No `events`, `laps`, `route`, `uuid`, `source_name`. Backend synthesizes `external_id` = `sha256(activity_type + "|" + start_iso_seconds + "|" + duration_s)`.

## Recommended Shortcut recipe (plain Shortcuts, Variant B — full)

1. Choose from Menu → `Activity type`: run, ride, walk, hike, swim, strength, yoga, hiit, elliptical, row.
2. Ask for Input (Date) → `Workout Start`.
3. Current Date → `Workout End`.
4. Get Time Between Dates (Seconds) → `Duration s`.
5. Find All Health Samples (Active Energy, between start/end) → `Energy Samples`.
6. Get Statistics → Sum → `Energy kcal`.
7. Find All Health Samples (Walking+Running Distance OR Cycling Distance) → `Distance Samples`.
8. Get Statistics → Sum, ×1000 → `Distance m`.
9. Find All Health Samples (Heart Rate, window) → `HR Samples`.
10. Get Statistics → Average → `Avg HR`.
11. Get Statistics → Maximum → `Max HR`.
12. Format Date `Workout Start` → ISO 8601 → `Start ISO`.
13. Format Date `Workout End` → ISO 8601 → `End ISO`.
14. Dictionary → build the JSON.
15. Get Contents of URL → POST `https://<railway-host>/api/ingest/apple-health/workouts`, headers `Content-Type: application/json` + `X-Apple-Health-Token: <token>`, Request Body = JSON.

## Open follow-ups

1. Toolbox Pro `Get Workouts` exact JSON shape unconfirmed (requires installing & dumping).
2. HAE workout `id` stability across re-syncs undocumented (likely HKWorkout UUID stringified).
3. The "When Workout Ends" automation trigger appears to pass no magic variables.
4. `HKWorkoutEvent` lap markers unreachable from any consumer Shortcuts path as of 2026-05.
5. `Find Health Samples` requires iPhone unlocked — automation may silently fail with phone asleep at workout end.

## Citations

- https://developer.apple.com/documentation/healthkit/hkworkoutactivitytype
- https://developer.apple.com/documentation/healthkit/hkworkout
- https://developer.apple.com/documentation/healthkit/workouts_and_activity_rings/reading_route_data
- https://support.apple.com/guide/shortcuts/intro-to-find-and-filter-actions-apd3c845e881/ios
- https://support.apple.com/guide/shortcuts/event-triggers-apd932ff833f/ios
- https://support.apple.com/guide/shortcuts/date-and-time-formats-apdfbad418ca/ios
- https://github.com/mm/heartbridge — real-world Shortcuts→Python pipeline
- https://github.com/Lybron/health-auto-export/wiki/API-Export---JSON-Format — HAE schema
- https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/ — HAE REST automation
- https://apps.apple.com/us/app/health-auto-export-json-csv/id1115567069
- https://apps.apple.com/us/app/toolbox-pro-for-shortcuts/id1476205977
- https://forum.actions.work/t/using-ios-shortcuts-to-get-apple-workout-data-into-obsidian/569
