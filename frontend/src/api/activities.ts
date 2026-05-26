import { fetchJson } from "./http";

export type ClassificationType =
  | "easy"
  | "tempo"
  | "intervals"
  | "race"
  | "recovery"
  | "endurance"
  | "mixed"
  | null;

export type ActivitySource = "apple_health" | "strava";

export interface ActivitySummary {
  id: number;
  strava_id: number;
  name: string;
  sport_type: string;
  source?: ActivitySource | null;
  external_id?: string | null;
  superseded_by_id?: number | null;
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
  /** Tagged running-shoe id; null when no shoe is tagged on this run. */
  shoe_id: number | null;
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
  hr_zone: number | null;
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
  type: string;
  distribution_buckets: ZoneBucket[];
  sensor_based?: boolean;
  points?: number;
}

export interface ActivityDetail extends ActivitySummary {
  laps: ActivityLap[];
  zones: ZoneDistribution[] | null;
  weather: Record<string, unknown> | null;
  streams_cached: boolean;
  hr_drift: number | null;
  pace_hr_decoupling: number | null;
  power_hr_decoupling: number | null;
  raw_data: Record<string, unknown> | null;
  /** True when HR zones were synthesized from raw HR samples rather than
   *  reported by the source device. Set by the Apple-workout detail builder. */
  zones_synthetic?: boolean;
  /** True when lap splits were derived by the ingestion pipeline
   *  (e.g. 1 km / 5 km auto-splits) rather than reported as real laps. */
  splits_synthetic?: boolean;
}

interface ActivityClassificationResult {
  classified: boolean;
  reason?: string;
  type?: Exclude<ClassificationType, null>;
  flags?: string[];
  confidence?: number;
  features?: Record<string, unknown>;
}

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

export function fetchActivity(id: number, source?: ActivitySource | null) {
  const qs = source ? `?source=${encodeURIComponent(source)}` : "";
  return fetchJson<ActivityDetail>(`/activities/${id}${qs}`);
}

export function fetchActivityStreams(
  id: number,
  source?: ActivitySource | null,
) {
  const qs = source ? `?source=${encodeURIComponent(source)}` : "";
  return fetchJson<Record<string, number[]>>(
    `/activities/${id}/streams${qs}`,
  );
}

export function reclassifyActivity(id: number) {
  return fetchJson<ActivityClassificationResult>(`/activities/${id}/classify`, {
    method: "POST",
  });
}

/**
 * Backend response shape for `PATCH /api/activities/{id}/shoe` — see
 * `backend/routers/activities.py::patch_activity_shoe`. The endpoint
 * dual-resolves to either a Strava `Activity` row or an Apple Health
 * `Workout` row and echoes which side it touched in `source`.
 */
export interface ActivityShoeUpdate {
  id: number;
  source: "strava" | "apple_health";
  shoe_id: number | null;
}

/**
 * Tag or untag a running shoe on an activity. Pass `shoeId=null` to
 * clear an existing tag.
 *
 * Note: unlike `fetchActivity`, the backend's `PATCH /shoe` endpoint
 * does NOT accept a `?source=` query — it always does the
 * Strava-first / Apple-fallback dual resolution. The `source` argument
 * here is kept for symmetry with `fetchActivity` and is forwarded as
 * `?source=` for forward-compat; the backend ignores unknown query
 * params today.
 */
export function patchActivityShoe(
  activityId: number,
  shoeId: number | null,
  source?: ActivitySource | null,
) {
  const qs = source ? `?source=${encodeURIComponent(source)}` : "";
  return fetchJson<ActivityShoeUpdate>(`/activities/${activityId}/shoe${qs}`, {
    method: "PATCH",
    body: JSON.stringify({ shoe_id: shoeId }),
  });
}
