const BASE_URL = "/api";

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    throw new Error(`API error: ${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

// ── Domain types ────────────────────────────────────────────────────────────

export type ClassificationType =
  | "easy"
  | "tempo"
  | "intervals"
  | "race"
  | "recovery"
  | "endurance"
  | "mixed"
  | null;

export interface ActivitySummary {
  id: number;
  strava_id: number;
  name: string;
  sport_type: string;
  start_date: string | null;
  start_date_local: string | null;
  elapsed_time: number | null;
  moving_time: number | null;
  distance: number | null;
  total_elevation: number | null;
  average_hr: number | null;
  max_hr: number | null;
  average_speed: number | null;
  max_speed: number | null;
  average_power: number | null;
  max_power: number | null;
  weighted_avg_power: number | null;
  average_cadence: number | null;
  calories: number | null;
  kilojoules: number | null;
  suffer_score: number | null;
  device_watts: boolean | null;
  workout_type: number | null;
  available_zones: string[] | null;
  enrichment_status: string;
  enriched_at: string | null;
  classification_type: ClassificationType;
  classification_flags: string[] | null;
  classified_at: string | null;
  weather_enriched: boolean;
  // Base-elevation context. ``base_elevation_m`` is the canonical
  // "where did this workout happen" altitude used for altitude-tier
  // flagging and correlations.
  elev_high_m: number | null;
  elev_low_m: number | null;
  base_elevation_m: number | null;
  elevation_enriched: boolean;
  location_id: number | null;
  start_lat: number | null;
  start_lng: number | null;
  rpe: number | null;
  user_notes: string | null;
  rated_at: string | null;
}

export interface ActivityLap {
  lap_index: number;
  name: string | null;
  elapsed_time: number | null;
  moving_time: number | null;
  distance: number | null;
  start_date: string | null;
  average_speed: number | null;
  max_speed: number | null;
  average_heartrate: number | null;
  max_heartrate: number | null;
  average_cadence: number | null;
  average_watts: number | null;
  total_elevation_gain: number | null;
  pace_zone: number | null;
  split: number | null;
  start_index: number | null;
  end_index: number | null;
}

export interface ZoneBucket {
  min: number;
  max: number;
  time: number;
}

export interface ZoneDistribution {
  type: string; // "heartrate" | "pace" | "power"
  distribution_buckets: ZoneBucket[];
  sensor_based?: boolean;
  points?: number;
}

export interface ActivityDetail extends ActivitySummary {
  laps: ActivityLap[];
  zones: ZoneDistribution[] | null;
  weather: Record<string, any> | null;
  streams_cached: boolean;
  raw_data: Record<string, any> | null;
}

export interface WeeklySummary {
  week_start: string;
  week_end: string;
  iso_week: string;
  totals: {
    activity_count: number;
    duration_s: number;
    distance_m: number;
    total_elevation_m: number;
    suffer_score: number;
    kilojoules: number;
    calories: number;
  };
  by_sport: Record<
    string,
    { count: number; duration_s: number; distance_m: number; kilojoules: number }
  >;
  run_breakdown: Record<
    string,
    { count: number; duration_s: number; distance_m: number }
  >;
  flags: {
    has_long_run: boolean;
    long_run_distance_m: number;
    has_speed_session: boolean;
    has_tempo: boolean;
    has_race: boolean;
    has_long_ride: boolean;
  };
  notable: {
    longest_activity_id: number | null;
    hardest_activity_id: number | null;
  };
  enrichment_pending: number;
  classification_pending: number;
}

// ── Activities ──────────────────────────────────────────────────────────────

export function fetchActivities(params?: {
  sport_type?: string;
  days?: number;
  limit?: number;
}) {
  const qs = new URLSearchParams();
  if (params?.sport_type) qs.set("sport_type", params.sport_type);
  if (params?.days) qs.set("days", String(params.days));
  if (params?.limit) qs.set("limit", String(params.limit));
  const query = qs.toString();
  return fetchJson<ActivitySummary[]>(
    `/activities${query ? `?${query}` : ""}`
  );
}

export function fetchActivity(id: number) {
  return fetchJson<ActivityDetail>(`/activities/${id}`);
}

export function fetchActivityStreams(id: number) {
  return fetchJson<Record<string, number[]>>(`/activities/${id}/streams`);
}

export function reclassifyActivity(id: number) {
  return fetchJson<any>(`/activities/${id}/classify`, { method: "POST" });
}

export function fetchSportTypes() {
  return fetchJson<string[]>("/activities/types");
}

// ── Weekly summary ──────────────────────────────────────────────────────────

export function fetchWeeklySummaries(weeks = 4) {
  return fetchJson<WeeklySummary[]>(`/summary/weekly?weeks=${weeks}`);
}

// Sleep
export function fetchSleepSessions(days = 30) {
  return fetchJson<any[]>(`/sleep?days=${days}`);
}

export function fetchSleepTrends(days = 30) {
  return fetchJson<any[]>(`/sleep/trends?days=${days}`);
}

// Recovery
export function fetchRecovery(days = 30) {
  return fetchJson<any[]>(`/recovery?days=${days}`);
}

export function fetchRecoveryTrends(days = 30) {
  return fetchJson<any[]>(`/recovery/trends?days=${days}`);
}

// Dashboard
export function fetchDashboardOverview() {
  return fetchJson<any>("/dashboard/overview");
}

// Chat / Analysis
export function askQuestion(question: string, model?: string) {
  return fetchJson<{ answer: string; model: string; tokens_used: number | null }>(
    "/chat/ask",
    {
      method: "POST",
      body: JSON.stringify({ question, model: model || undefined }),
    }
  );
}

export function fetchDailyBriefing(model?: string) {
  const qs = model ? `?model=${model}` : "";
  return fetchJson<{ answer: string; model: string }>(`/chat/daily-briefing${qs}`);
}

export function fetchWorkoutAnalysis(activityId: number, model?: string) {
  const qs = model ? `?model=${model}` : "";
  return fetchJson<{ answer: string; model: string }>(`/chat/workout/${activityId}${qs}`);
}

export function fetchAvailableModels() {
  return fetchJson<{ models: string[] }>("/chat/models");
}

// Sync
export function triggerSync(source = "all") {
  return fetchJson<{ status: string; synced: Record<string, number> }>("/sync/trigger", {
    method: "POST",
    body: JSON.stringify({ source }),
  });
}

export function fetchSyncStatus() {
  return fetchJson<Record<string, any>>("/sync/status");
}
