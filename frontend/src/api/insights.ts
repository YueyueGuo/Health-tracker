// ── Types ──────────────────────────────────────────────────────────────
// Keep these in sync with backend/services/insights.py (Pydantic models)
// and backend/services/training_metrics.py (snapshot dicts).

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
  laps: any[];
  weather: any | null;
  pre_workout_sleep: any | null;
  historical_comparison: {
    classification: string;
    sample_size: number;
    window_days: number;
    pace_percentile: number | null;
    effort_percentile: number | null;
  } | null;
}

export interface FullSnapshot {
  today: string;
  training_load: TrainingLoadSnapshot;
  sleep: SleepSnapshot;
  recovery: RecoverySnapshot;
  latest_workout: LatestWorkoutSnapshot | null;
  recent_activities: any[];
}

export interface DailyRecommendationResponse {
  recommendation: DailyRecommendation;
  inputs: FullSnapshot;
  model: string;
  generated_at: string;
  cached: boolean;
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

const BASE_URL = "/api";

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText);
    throw new Error(`API error ${resp.status}: ${text}`);
  }
  return resp.json();
}

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
