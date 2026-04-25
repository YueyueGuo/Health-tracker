// ── Types ──────────────────────────────────────────────────────────────
// Keep these in sync with backend/services/insight_schemas.py and
// backend/services/snapshot_models.py.
//
// Snapshot type-sync checklist:
// 1. When a backend Pydantic snapshot model changes, update the matching
//    interface here in the same PR.
// 2. Check nullability carefully: backend ``foo: X | None = None`` usually
//    maps to ``foo: X | null`` unless the field is intentionally omitted.
// 3. Verify nested latest-workout fields against
//    ``backend/services/workout_snapshot.py`` because that payload is still
//    assembled manually before Pydantic validation.
// 4. Re-run ``npm test``, ``npm run typecheck``, and ``npm run build`` after
//    changing either side of the contract.
// 5. ``tests/test_services/test_snapshot_contract_drift.py`` asserts field-name
//    parity between this file and ``snapshot_models.py``. It catches the common
//    "added on one side, forgot the other" drift, but it does NOT check types
//    or nullability — those are still manual.

import { fetchJson } from "./http";

export type Intensity = "rest" | "recovery" | "easy" | "moderate" | "quality";
export type Confidence = "high" | "medium" | "low";

export interface DailyRecommendation {
  intensity: Intensity;
  suggestion: string;
  rationale: string[];
  concerns: string[];
  confidence: Confidence;
}

export interface TrainingLoadSnapshot {
  acute_load_7d: number;
  chronic_load_28d: number;
  acwr: number | null;
  monotony: number | null;
  strain: number | null;
  days_since_hard: number | null;
  last_hard_date: string | null;
  classification_counts_7d: Record<string, number>;
  classification_counts_28d: Record<string, number>;
  daily_loads: { date: string; value: number }[];
  activity_count_7d: number;
}

export interface SleepSnapshot {
  last_night_date?: string;
  last_night_score: number | null;
  last_night_duration_min: number | null;
  last_night_deep_min?: number | null;
  last_night_rem_min?: number | null;
  last_night_hrv: number | null;
  last_night_resting_hr?: number | null;
  avg_score_7d: number | null;
  avg_duration_min_7d: number | null;
  avg_hrv_7d: number | null;
  sleep_debt_min: number | null;
  nights_of_data: number;
}

export interface RecoverySnapshot {
  today_date?: string;
  today_score: number | null;
  today_hrv: number | null;
  today_resting_hr: number | null;
  avg_score_7d: number | null;
  trend: "improving" | "stable" | "declining" | null;
}

export interface WorkoutLapSnapshot {
  index: number;
  distance_m: number | null;
  moving_time_s: number | null;
  pace: string | null;
  avg_hr: number | null;
  avg_watts: number | null;
  pace_zone: number | null;
  hr_zone: number | null;
}

export interface HrZoneRangeSnapshot {
  zone: number;
  min: number;
  max: number;
}

export interface HrZonesSnapshot {
  z1_pct?: number | null;
  z2_pct?: number | null;
  z3_pct?: number | null;
  z4_pct?: number | null;
  z5_pct?: number | null;
  z6_pct?: number | null;
  z7_pct?: number | null;
  dominant_zone: number;
  total_minutes: number;
  bucket_count: number;
  ranges: HrZoneRangeSnapshot[];
}

export interface WorkoutWeatherSnapshot {
  temp_c: number | null;
  feels_like_c: number | null;
  humidity: number | null;
  wind_speed_ms: number | null;
  conditions: string | null;
}

export interface PreWorkoutSleepSnapshot {
  date: string;
  score: number | null;
  duration_min: number | null;
  hrv: number | null;
  deep_min: number | null;
  rem_min: number | null;
}

export interface HistoricalComparisonSnapshot {
  classification: string;
  sample_size: number;
  window_days: number;
  pace_percentile: number | null;
  effort_percentile: number | null;
}

export interface LatestWorkoutSnapshot {
  id: number;
  strava_id: number;
  name: string;
  sport_type: string;
  classification_type: string | null;
  classification_flags: string[];
  start_date: string | null;
  start_date_local: string | null;
  distance_m: number | null;
  moving_time_s: number | null;
  elapsed_time_s: number | null;
  total_elevation_m: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_speed_ms: number | null;
  pace: string | null;
  avg_power_w: number | null;
  weighted_avg_power_w: number | null;
  kilojoules: number | null;
  suffer_score: number | null;
  calories: number | null;
  laps: WorkoutLapSnapshot[];
  hr_zones: HrZonesSnapshot | null;
  hr_drift: number | null;
  pace_hr_decoupling: number | null;
  power_hr_decoupling: number | null;
  weather: WorkoutWeatherSnapshot | null;
  pre_workout_sleep: PreWorkoutSleepSnapshot | null;
  historical_comparison: HistoricalComparisonSnapshot | null;
}

export interface GoalSnapshot {
  id: number;
  race_type: string;
  description: string | null;
  target_date: string;
  days_until: number;
  weeks_until: number;
  phase: string;
  is_primary: boolean;
  status: string;
}

export interface GoalsSnapshot {
  primary: GoalSnapshot | null;
  secondary: GoalSnapshot[];
}

export interface MeanSdSnapshot {
  mean: number;
  sd: number;
}

export interface SportBaselineSnapshot {
  sample_size: number;
  pace_s_per_km: MeanSdSnapshot | null;
  avg_hr: MeanSdSnapshot | null;
  avg_power_w: MeanSdSnapshot | null;
}

export type BaselinesSnapshot = Record<string, SportBaselineSnapshot | null>;

export interface RecentRpeSnapshot {
  activity_id: number;
  date: string;
  sport_type: string;
  classification: string | null;
  rpe: number;
  notes: string | null;
  avg_hr: number | null;
  suffer_score: number | null;
}

export interface FeedbackDeclineSnapshot {
  date: string;
  reason: string | null;
}

export interface FeedbackSummarySnapshot {
  accepted: number;
  declined: number;
  total: number;
  recent_declines: FeedbackDeclineSnapshot[];
}

export interface EnvironmentalSnapshot {
  last_night_bed_temp_c: number;
  last_night_date: string | null;
}

export interface RecentActivitySnapshot {
  date: string;
  sport: string;
  classification: string | null;
  duration_min: number | null;
  distance_km: number | null;
  avg_hr: number | null;
  suffer_score: number | null;
  pace: string | null;
}

export interface FullSnapshot {
  today: string;
  training_load: TrainingLoadSnapshot;
  sleep: SleepSnapshot;
  recovery: RecoverySnapshot;
  latest_workout: LatestWorkoutSnapshot | null;
  recent_activities: RecentActivitySnapshot[];
  goals: GoalsSnapshot;
  baselines: BaselinesSnapshot;
  recent_rpe: RecentRpeSnapshot[];
  feedback_summary: FeedbackSummarySnapshot;
  environmental: EnvironmentalSnapshot | null;
}

export interface DailyRecommendationResponse {
  recommendation: DailyRecommendation;
  inputs: FullSnapshot;
  model: string;
  generated_at: string;
  cached: boolean;
  cache_key: string;
  recommendation_date: string;
}

export interface NotableSegment {
  label: string;
  detail: string;
}

export interface WorkoutInsight {
  headline: string;
  takeaway: string;
  notable_segments: NotableSegment[];
  vs_history: string | null;
  flags: string[];
}

export interface WorkoutInsightResponse {
  activity_id: number;
  workout: LatestWorkoutSnapshot;
  insight: WorkoutInsight;
  model: string;
  generated_at: string;
  cached: boolean;
}

// ── Fetchers ───────────────────────────────────────────────────────────

export function fetchTrainingMetrics() {
  return fetchJson<FullSnapshot>("/insights/training-metrics");
}

export function fetchDailyRecommendation(refresh = false, model?: string) {
  const qs = new URLSearchParams();
  if (refresh) qs.set("refresh", "true");
  if (model) qs.set("model", model);
  const query = qs.toString();
  return fetchJson<DailyRecommendationResponse>(
    `/insights/daily-recommendation${query ? `?${query}` : ""}`
  );
}

export function fetchLatestWorkoutInsight(opts?: {
  activityId?: number;
  refresh?: boolean;
  model?: string;
}) {
  const qs = new URLSearchParams();
  if (opts?.activityId) qs.set("activity_id", String(opts.activityId));
  if (opts?.refresh) qs.set("refresh", "true");
  if (opts?.model) qs.set("model", opts.model);
  const query = qs.toString();
  return fetchJson<WorkoutInsightResponse>(
    `/insights/latest-workout${query ? `?${query}` : ""}`
  );
}
