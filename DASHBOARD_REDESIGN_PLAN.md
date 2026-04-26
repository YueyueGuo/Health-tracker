# Dashboard Redesign — "Right Now" Status + Environment + Frontier-Model A/B

## Context

The current landing page ([frontend/src/components/Dashboard.tsx](frontend/src/components/Dashboard.tsx)) shows weekly totals — activities, training time, last sleep score, recovery score — plus an LLM recommendation card and the latest workout. It does not answer "how am I doing right now": there's no last-night sleep breakdown, no HRV, no HRV trend, no training-load gauge, no environmental context.

A separate audit confirmed almost every data point we fetch is persisted (1,762 activities, 622 sleep sessions, 1,191 weather snapshots, etc.). The signal exists; the dashboard just doesn't surface it. This plan reuses existing snapshot services (`sleep_recovery_snapshot`, `training_load_snapshot`) for sleep/recovery/load tiles, adds a small environment tile fed by Open-Meteo's free forecast + air-quality APIs, and lets the user A/B-compare frontier LLM models on the recommendation and latest-workout cards.

**Side findings (out of scope here, tracked separately):**
- Whoop refresh token is dead. Last successful sync 2026-04-25 03:13; every sync since hits HTTP 400 `invalid_request`. Fix = re-authorize at `/api/auth/whoop`.
- Eight Sleep already stores nightly RMSSD HRV; we use it as the primary HRV source for the dashboard, with Whoop as a fallback once that pipeline is healthy again.

---

## Work breakdown — five parallelizable chunks

Each chunk is a self-contained branch + PR. Chunks **A, B, C run fully in parallel** (no shared files). **D depends on A+B** for the response shape; **E depends on C** for the model-list endpoint. Realistic parallelism: A/B/C land same day, D + E land next.

The seam between chunks is the JSON contract — keep the response shapes in this plan as the source of truth so agents working in parallel don't drift. The existing snapshot-contract drift test ([tests/test_services/test_snapshot_contract_drift.py](tests/test_services/test_snapshot_contract_drift.py)) catches Pydantic ↔ TS interface mismatches at CI time.

| Chunk | Branch suggestion | Scope summary | Depends on |
|---|---|---|---|
| **A** | `feat/dashboard-today-snapshot` | `RecoverySnapshot` HRV trend; `acwr_band` helper; `/api/dashboard/today` handler; backend tests | none |
| **B** | `feat/openmeteo-environment` | Forecast + AQ/pollen client methods; `services/environment.py`; in-memory cache; tests | none |
| **C** | `feat/llm-frontier-models` | Add `gpt-5.5`/`gpt-5.5-pro`/`claude-opus-4-7` to provider registry; flip `dashboard_model` default; `/api/insights/models` endpoint | none |
| **D** | `feat/dashboard-tiles-frontend` | New tile components, `Dashboard.tsx` rewrite, `fetchDashboardToday`, contract-drift mirroring, tile tests | A, B |
| **E** | `feat/llm-model-picker-frontend` | `ModelPicker.tsx`; wire into recommendation + workout cards; `fetchAvailableModels`; tests | C |

Per-chunk detail follows below — each section's "Files" lists everything that chunk owns. No file appears in two chunks (avoids merge conflicts).

---

## Backend changes

### 1. New endpoint: `GET /api/dashboard/today`

Add the handler to [backend/routers/dashboard.py](backend/routers/dashboard.py) (no new router file). Leave `/api/dashboard/overview` untouched so existing callers keep working.

Composition (all reuse, no new abstractions):

```python
sleep      = await sleep_recovery_snapshot.get_sleep_snapshot(db, days=14)
recovery   = await sleep_recovery_snapshot.get_recovery_snapshot(db, days=7)
training   = await training_load_snapshot.get_training_load_snapshot(db, days=42)
env        = await environment.fetch_environment_today(db)   # new, see §3
```

Response shape (flat, dashboard-tailored — not the full LLM snapshot):

```jsonc
{
  "as_of": "2026-04-25T08:12:00-04:00",
  "sleep": {
    "last_night_score": 89,
    "last_night_duration_min": 500,
    "last_night_deep_min": 92,
    "last_night_rem_min": 118,
    "last_night_date": "2026-04-25"
  },
  "recovery": {
    "today_hrv": 77.3,
    "today_resting_hr": 49.0,
    "hrv_baseline_7d": 72.1,
    "hrv_trend": "up" | "down" | "flat",
    "hrv_source": "eight_sleep" | "whoop"
  },
  "training": {
    "yesterday_stress": 78.2,
    "week_to_date_load": 412.1,
    "acwr": 1.12,
    "acwr_band": "optimal" | "elevated" | "detraining" | "caution",
    "days_since_hard": 2
  },
  "environment": { ... } | null
}
```

`acwr_band` is computed server-side via a new helper next to the snapshot:
- `< 0.8` → `detraining`
- `0.8–1.3` → `optimal`
- `1.3–1.5` → `caution`
- `> 1.5` → `elevated`

Also expose `GET /api/insights/models` returning the keys from `LLMSettings.available_dashboard_models()` (see §5) so the frontend picker isn't hardcoded.

### 2. Recovery snapshot: Eight Sleep HRV as primary

Modify [backend/services/sleep_recovery_snapshot.py](backend/services/sleep_recovery_snapshot.py) `get_recovery_snapshot`:

- Pull last 7 `SleepSession` rows in addition to existing `Recovery` rows.
- New fields populated:
  - `today_hrv = sleep_sessions[0].hrv if non-null else recovery.hrv`
  - `today_resting_hr = sleep_sessions[0].avg_hr if non-null else recovery.resting_hr`
  - `hrv_baseline_7d = mean of non-null hrv values in last 7 sleep_sessions` (falls back to Whoop average if Eight Sleep absent)
  - `hrv_source ∈ {"eight_sleep", "whoop", None}` — record which source the trend was computed from
  - `hrv_trend`:
    - `"up"` if `today_hrv ≥ baseline + 3 ms`
    - `"down"` if `today_hrv ≤ baseline − 3 ms`
    - `"flat"` otherwise (RMSSD has ~5ms day-to-day noise; 3ms threshold is reasonable for a single-night signal)
- Existing `trend` field (improving/stable/declining for `recovery_score`) **stays**. Don't conflate with HRV trend.
- Update [backend/services/snapshot_models.py](backend/services/snapshot_models.py) `RecoverySnapshot` to add `hrv_baseline_7d`, `hrv_trend`, `hrv_source`. The contract-drift test will fail until [frontend/src/api/insights.ts](frontend/src/api/insights.ts) mirrors the change.
- Prep-branch invariant: until this chunk computes real HRV fields, `get_recovery_snapshot()` must emit those three keys explicitly as `None` in every payload branch. `validate_snapshot()` validates defaults but returns the original dict, so Pydantic defaults alone do not make the runtime `/api/insights/training-metrics` contract match the TypeScript interface.

### 3. Open-Meteo client extensions + environment composer

Extend [backend/clients/openmeteo.py](backend/clients/openmeteo.py) — do **not** split files. Reuse existing `_throttle()`, `_record_call()`, and `WeatherRateLimitError` machinery.

```python
async def get_forecast_today(self, lat: float, lng: float) -> dict | None
async def get_air_quality_and_pollen(self, lat: float, lng: float) -> dict | None
```

- Forecast: `https://api.open-meteo.com/v1/forecast` with `current=temperature_2m,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,weather_code,wind_speed_10m_max&forecast_days=1`
- Air quality + pollen (single endpoint, single call): `https://air-quality-api.open-meteo.com/v1/air-quality` with `current=european_aqi,us_aqi,alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,olive_pollen,ragweed_pollen`

Each returns a normalized dict; returns `None` on empty response.

New file: `backend/services/environment.py` exporting `fetch_environment_today(db) -> dict | None`:

- Reads default `UserLocation` (`is_default=True`) for lat/lng. Returns `None` if none configured.
- Module-level in-memory TTL cache keyed by `(lat, lng, hour_bucket)`. Plain `dict[tuple, tuple[monotonic_ts, payload]]` with 1h expiry. No new dependency.
- `asyncio.gather(forecast, air_quality)` for parallel fetch.
- Wrapped in `try/except` at the router level so a transient Open-Meteo failure doesn't crash the dashboard (env tile shows "weather unavailable").
- **Not persisted** — environment data is intentionally ephemeral.

Add `EnvironmentTodaySnapshot` Pydantic model to `snapshot_models.py` (do not reuse the existing `EnvironmentalSnapshot` — that's a much smaller bed-temp-only model used by the LLM snapshot path; different scope, different consumers).

### 4. Tooltip text shipped as a server-side constant

ACWR tooltip text in `acwr_band` helper docstring (and re-exported as `ACWR_TOOLTIP` constant from `training_load_snapshot.py`):

> "Acute:Chronic Workload Ratio — last 7 days of training load divided by last 28 days. >1.5 elevated injury risk; 0.8–1.3 optimal; <0.8 detraining."

Frontend reads it from a constant in the API module rather than hardcoding strings in JSX, so wording updates are one-line.

### 5. LLM model registry + frontier defaults

[backend/services/llm_providers.py](backend/services/llm_providers.py):
- `AnthropicProvider.MODELS`: add `"claude-opus-4-7": "claude-opus-4-7"` (current Anthropic flagship per env note).
- `OpenAIProvider.MODELS`: add `"gpt-5.5": "gpt-5.5"` and `"gpt-5.5-pro": "gpt-5.5-pro"`. Aliases resolve to dated snapshots server-side (`gpt-5.5-2026-04-23` and `gpt-5.5-pro-2026-04-23`).
- `GoogleProvider.MODELS`: `gemini-2.5-pro` already there per CLAUDE.md.

[backend/config.py](backend/config.py) `LLMSettings`:
- `dashboard_model: str = "gpt-5.5"` (was `"gpt-4o"`)
- `dashboard_fallback_models: list[str] = ["claude-opus-4-7", "gemini-2.5-pro", "gpt-4o"]`
- New classmethod `available_dashboard_models() -> list[str]` returning the four keys in frontier-preference order; surfaced via `GET /api/insights/models`.

[backend/services/llm_providers.py](backend/services/llm_providers.py) `OpenAIProvider.MODELS`:
- Add `"gpt-5.5": "gpt-5.5"` (alias resolves to current snapshot `gpt-5.5-2026-04-23`, released 2026-04-24 per [OpenAI API docs](https://developers.openai.com/api/docs/models/gpt-5.5)).
- Add `"gpt-5.5-pro": "gpt-5.5-pro"` for the higher-precision variant — useful if the user wants to A/B test pro vs base on a specific card.

Token-cost note (from exploration): daily-recommendation prompt is ~2k input tokens, latest-workout ~1k. Even at GPT-5.5 / Opus 4.7 pricing this is well under 1¢ per call and cached per inputs hash — A/B comparison cost is negligible.

---

## Frontend changes

### 6. API module + types

Extend [frontend/src/api/dashboard.ts](frontend/src/api/dashboard.ts) (same domain — don't create a new file):

```ts
export interface DashboardToday {
  as_of: string;
  sleep: SleepTodayPayload;
  recovery: RecoveryTodayPayload;     // includes hrv_trend, hrv_source, hrv_baseline_7d
  training: TrainingTodayPayload;     // includes acwr_band
  environment: EnvironmentToday | null;
}
export const ACWR_TOOLTIP: string;     // mirrored from backend constant
export function fetchDashboardToday(): Promise<DashboardToday>;
```

Extend [frontend/src/api/insights.ts](frontend/src/api/insights.ts):
- Mirror the new `RecoverySnapshot` fields (otherwise the contract-drift test fails).
- Add `fetchAvailableModels()` against `/api/insights/models`.

### 7. Dashboard layout + tile components

[frontend/src/components/Dashboard.tsx](frontend/src/components/Dashboard.tsx):
- Replace `useApi(fetchDashboardOverview)` with `useApi(fetchDashboardToday)`.
- Drop the four inline tile divs.
- Keep `RecommendationCard`, `LatestWorkoutCard`, `WeeklySummaryCards` — those still belong on the landing page.

New folder `frontend/src/components/dashboard/`:
- `SleepTile.tsx` — score (color-graded), duration `Xh Ym`, deep + REM bars (stacked)
- `RecoveryTile.tsx` — RHR (bpm), HRV (ms), trend arrow `↑`/`↓`/`→` color-coded, source pill (`Eight Sleep` / `Whoop`)
- `TrainingLoadTile.tsx` — yesterday's stress, WTD load, ACWR chip with band-colored background and `title={ACWR_TOOLTIP}` (native HTML tooltip — matches the existing pattern in [Layout.tsx:36](frontend/src/components/Layout.tsx))
- `EnvironmentTile.tsx` — current temp + condition icon, high/low, wind, AQI value with a band color, top 1–2 pollen species when above threshold

CSS: add `.metric-grid-4` to the existing global stylesheet:
```css
.metric-grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
@media (max-width: 720px) { .metric-grid-4 { grid-template-columns: repeat(2, 1fr); } }
```

### 8. Model picker

New file `frontend/src/components/ModelPicker.tsx` (~30 LOC):
```tsx
interface Props { value: string; onChange: (m: string) => void; models: string[]; }
```
Styled `<select>` matching existing button look.

Wire into [RecommendationCard.tsx](frontend/src/components/RecommendationCard.tsx) and [LatestWorkoutCard.tsx](frontend/src/components/LatestWorkoutCard.tsx) header rows next to the existing `Refresh` / `cached…` controls.

**State location: per-card local React state.** Reasoning:
- Cards are independent — A/B comparison wants to swap them separately.
- URL params would force routing changes the rest of the app doesn't need.
- Existing `fetchDailyRecommendation(refresh, model)` and `fetchLatestWorkoutInsight({model})` already accept `model`. Backend cache is keyed by inputs hash + model, so switching = different cache slot, switching back = instant.
- Default = first entry from `fetchAvailableModels()`, which the backend orders by frontier preference.

---

## Tests

### Breaks
- [frontend/src/components/Dashboard.test.tsx](frontend/src/components/Dashboard.test.tsx) — every assertion against the old four-tile shape (`19.3 mi`, `5h 42m`, `91`, sport-breakdown, etc.) needs rewriting. Provide a `fetchDashboardToday` mock and assert each tile renders correct derived strings.
- [tests/test_services/test_snapshot_contract_drift.py](tests/test_services/test_snapshot_contract_drift.py) will fail until `frontend/src/api/insights.ts` mirrors the new `RecoverySnapshot` fields. Intentional — it's the safety net.

### New
- `tests/test_routers/test_dashboard_today.py` — DB fixtures (14 sleep sessions, 30 days of activities), assert response shape, ACWR band thresholds, HRV trend computation (up/down/flat at the 3ms boundary). Mock `fetch_environment_today` to skip network.
- `tests/test_services/test_environment.py` — patch `httpx.AsyncClient`, assert in-memory cache hits within 1h and misses past it; assert no default `UserLocation` returns `None`.
- `tests/test_clients/test_openmeteo_air_quality.py` — fixture JSON, assert AQI + pollen parsing for both methods.
- New tile component tests: `SleepTile.test.tsx`, `RecoveryTile.test.tsx`, `TrainingLoadTile.test.tsx`, `EnvironmentTile.test.tsx`, `ModelPicker.test.tsx`.

---

## Migration concerns

None. No new SQL columns, no Alembic revision. Eight Sleep HRV already lives on `sleep_sessions.hrv`. Environment data is intentionally non-persistent.

---

## Verification

**Backend:**
```bash
.venv/bin/pytest tests/test_routers/test_dashboard_today.py \
                 tests/test_services/test_environment.py \
                 tests/test_services/test_snapshot_contract_drift.py \
                 tests/test_clients/test_openmeteo_air_quality.py -x
```

**Backend manual:**
```bash
uvicorn backend.main:app --reload
curl -s localhost:8000/api/dashboard/today | jq
curl -s localhost:8000/api/insights/models | jq
```
Confirm `environment` populated when a default `UserLocation` exists; `null` when none.

**Frontend:**
```bash
cd frontend && npm test && npm run typecheck && npm run build
```

**Manual QA:**
1. Load `/` — confirm 4 tiles render real values, no console errors.
2. Resize to 700px wide — tile grid collapses to 2-wide.
3. Hover ACWR chip — native tooltip shows the explanation.
4. Switch recommendation card model picker to `gpt-5` — card refetches; switch back to `claude-opus-4-7` — cached response returns instantly.
5. Same flow for the latest-workout card independently.
6. Disable network momentarily — environment tile shows graceful empty state, rest of the dashboard still works.

---

## Critical files

**Backend (new):**
- `backend/services/environment.py`
- `tests/test_routers/test_dashboard_today.py`
- `tests/test_services/test_environment.py`
- `tests/test_clients/test_openmeteo_air_quality.py`

**Backend (modified):**
- [backend/routers/dashboard.py](backend/routers/dashboard.py) — new `/today` handler
- [backend/routers/insights.py](backend/routers/insights.py) — `/models` endpoint
- [backend/services/sleep_recovery_snapshot.py](backend/services/sleep_recovery_snapshot.py) — Eight Sleep HRV trend logic
- [backend/services/training_load_snapshot.py](backend/services/training_load_snapshot.py) — `acwr_band` helper, `ACWR_TOOLTIP` constant
- [backend/services/snapshot_models.py](backend/services/snapshot_models.py) — extend `RecoverySnapshot`, add `EnvironmentTodaySnapshot`
- [backend/clients/openmeteo.py](backend/clients/openmeteo.py) — forecast + air-quality methods
- [backend/services/llm_providers.py](backend/services/llm_providers.py) — model registry additions
- [backend/config.py](backend/config.py) — frontier defaults + `available_dashboard_models()`

**Frontend (new):**
- `frontend/src/components/dashboard/SleepTile.tsx`
- `frontend/src/components/dashboard/RecoveryTile.tsx`
- `frontend/src/components/dashboard/TrainingLoadTile.tsx`
- `frontend/src/components/dashboard/EnvironmentTile.tsx`
- `frontend/src/components/ModelPicker.tsx`
- (+ co-located `.test.tsx` for each)

**Frontend (modified):**
- [frontend/src/components/Dashboard.tsx](frontend/src/components/Dashboard.tsx) — replace tiles
- [frontend/src/components/RecommendationCard.tsx](frontend/src/components/RecommendationCard.tsx) — picker integration
- [frontend/src/components/LatestWorkoutCard.tsx](frontend/src/components/LatestWorkoutCard.tsx) — picker integration
- [frontend/src/api/dashboard.ts](frontend/src/api/dashboard.ts) — `fetchDashboardToday`, types, `ACWR_TOOLTIP`
- [frontend/src/api/insights.ts](frontend/src/api/insights.ts) — mirror new `RecoverySnapshot` fields, `fetchAvailableModels`
- [frontend/src/components/Dashboard.test.tsx](frontend/src/components/Dashboard.test.tsx) — rewrite for new shape
- Global CSS — add `.metric-grid-4` rule

---

## File ownership per chunk (no overlap)

### Chunk A — `feat/dashboard-today-snapshot`
**Owns:**
- `backend/services/sleep_recovery_snapshot.py` (modify `get_recovery_snapshot`)
- `backend/services/training_load_snapshot.py` (add `acwr_band`, `ACWR_TOOLTIP`)
- `backend/services/snapshot_models.py` (extend `RecoverySnapshot`; do NOT add `EnvironmentTodaySnapshot` here — that's chunk B)
- `backend/routers/dashboard.py` (add `/today` handler; import env composer from B as a soft dep — see "Coordination" below)
- `tests/test_routers/test_dashboard_today.py` (new)
- `tests/test_services/test_snapshot_recovery_hrv.py` (new — focused unit test for HRV trend logic)

**Coordination:** the `/today` handler imports `fetch_environment_today` from chunk B. To avoid blocking, A can land with a stub `from backend.services.environment import fetch_environment_today` guarded by `try/except ImportError` returning `None`, then B replaces the stub. Cleaner alternative: A and B both target the same branch off main, B merges into main first.

### Chunk B — `feat/openmeteo-environment`
**Owns:**
- `backend/clients/openmeteo.py` (add `get_forecast_today`, `get_air_quality_and_pollen`)
- `backend/services/environment.py` (new — `fetch_environment_today` + in-memory TTL cache)
- `backend/services/snapshot_models.py` — **add ONLY `EnvironmentTodaySnapshot`** (Chunk A only modifies `RecoverySnapshot`; pre-coordinate by adding both Pydantic models in a single trivial commit on main first if working truly in parallel, or have B merge after A)
- `tests/test_services/test_environment.py` (new)
- `tests/test_clients/test_openmeteo_air_quality.py` (new)

**Coordination on `snapshot_models.py`:** to avoid two parallel branches editing the same file, the easiest pattern is a **5-minute prep commit on main** that adds the empty `EnvironmentTodaySnapshot` and the empty extension fields to `RecoverySnapshot`. Then A and B fill them in independently. Mention this in each agent's prompt.

### Chunk C — `feat/llm-frontier-models`
**Owns:**
- `backend/services/llm_providers.py` (extend `MODELS` dicts on `AnthropicProvider` and `OpenAIProvider`)
- `backend/config.py` (flip `dashboard_model` default; update `dashboard_fallback_models`; add `available_dashboard_models()` classmethod)
- `backend/routers/insights.py` (add `GET /models` endpoint)
- `tests/test_services/test_llm_providers.py` (extend — assert new models registered, fallback chain ordering)
- `tests/test_routers/test_insights_models_endpoint.py` (new)

### Chunk D — `feat/dashboard-tiles-frontend` (depends on A + B)
**Owns:**
- `frontend/src/components/Dashboard.tsx` (rewrite tile section)
- `frontend/src/components/Dashboard.test.tsx` (rewrite for new shape)
- `frontend/src/components/dashboard/SleepTile.tsx` + `.test.tsx` (new)
- `frontend/src/components/dashboard/RecoveryTile.tsx` + `.test.tsx` (new)
- `frontend/src/components/dashboard/TrainingLoadTile.tsx` + `.test.tsx` (new)
- `frontend/src/components/dashboard/EnvironmentTile.tsx` + `.test.tsx` (new)
- `frontend/src/api/dashboard.ts` (add `fetchDashboardToday`, types, `ACWR_TOOLTIP`)
- `frontend/src/api/insights.ts` — mirror new `RecoverySnapshot` fields ONLY (do NOT add model-list types — that's chunk E)
- Global CSS file (add `.metric-grid-4` rule)

**Coordination on `insights.ts`:** D adds recovery-snapshot fields, E adds model-list helper. Same file, different exports. Either land D first (E rebases) or both target the same intermediate branch.

### Chunk E — `feat/llm-model-picker-frontend` (depends on C)
**Owns:**
- `frontend/src/components/ModelPicker.tsx` + `.test.tsx` (new)
- `frontend/src/components/RecommendationCard.tsx` (wire picker into header)
- `frontend/src/components/LatestWorkoutCard.tsx` (wire picker into header)
- `frontend/src/api/insights.ts` — add ONLY `fetchAvailableModels` + `AvailableModelsResponse` type
- Existing tests on the two cards updated for new picker prop

---

## Recommended execution order

1. **Prep commit on main** (~5 min, single agent): add empty `EnvironmentTodaySnapshot` Pydantic stub and empty `RecoverySnapshot` field stubs to `snapshot_models.py`. Eliminates the only file conflict between A and B.
2. **Spawn A, B, C in parallel** as three separate agents on three separate branches off main (CLAUDE.md note: each agent must be on its own branch — don't co-locate).
3. After A and B land, **spawn D**.
4. After C lands, **spawn E**.
5. Final smoke test: pull main, run the full verification block above.
