import { fetchJson } from "./http";

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

export function fetchWeeklySummaries(weeks = 4) {
  return fetchJson<WeeklySummary[]>(`/summary/weekly?weeks=${weeks}`);
}
