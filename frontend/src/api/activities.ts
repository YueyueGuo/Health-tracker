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
  raw_data: Record<string, unknown> | null;
}

export interface ActivityClassificationResult {
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

export function fetchActivity(id: number) {
  return fetchJson<ActivityDetail>(`/activities/${id}`);
}

export function fetchActivityStreams(id: number) {
  return fetchJson<Record<string, number[]>>(`/activities/${id}/streams`);
}

export function reclassifyActivity(id: number) {
  return fetchJson<ActivityClassificationResult>(`/activities/${id}/classify`, {
    method: "POST",
  });
}

export function fetchSportTypes() {
  return fetchJson<string[]>("/activities/types");
}
