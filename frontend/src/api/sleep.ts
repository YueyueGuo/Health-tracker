import { fetchJson } from "./http";

export interface WakeEvent {
  type: "awake" | "out";
  duration_sec: number;
  offset_sec: number;
}

export interface SleepSession {
  id: number;
  source: string;
  external_id?: string | null;
  date: string;
  bed_time: string | null;
  wake_time: string | null;
  total_duration: number | null; // minutes
  deep_sleep: number | null; // minutes
  rem_sleep: number | null; // minutes
  light_sleep: number | null; // minutes
  awake_time: number | null; // minutes
  sleep_score: number | null;
  sleep_fitness_score: number | null;
  avg_hr: number | null;
  hrv: number | null;
  respiratory_rate: number | null;
  bed_temp: number | null;
  tnt_count: number | null;
  latency: number | null; // seconds
  // Only available on recent 10 nights
  wake_count?: number | null;
  waso_duration?: number | null; // minutes
  out_of_bed_count?: number | null;
  out_of_bed_duration?: number | null; // minutes
  wake_events?: WakeEvent[] | null;
  // Whoop-only extras (null on Eight Sleep rows).
  sleep_efficiency?: number | null; // %, time asleep / in bed
  sleep_consistency?: number | null; // %, schedule regularity
  sleep_need_baseline_min?: number | null;
  sleep_debt_min?: number | null;
}

export type SleepSource = "whoop" | "eight_sleep";

export function fetchSleepSessions(days = 30): Promise<SleepSession[]> {
  return fetchJson<SleepSession[]>(`/sleep?days=${days}`);
}

export function fetchSleepTrends(days = 30): Promise<SleepSession[]> {
  return fetchJson<SleepSession[]>(`/sleep/trends?days=${days}`);
}

export function fetchLatestSleep(): Promise<SleepSession | null> {
  return fetchJson<SleepSession | null>(`/sleep/latest`);
}

/**
 * Fetch the latest sleep session for a single source. Used by the
 * sleep details card so the WHOOP and Eight Sleep columns each bind
 * to their own most-recent row instead of fighting over /sleep/latest.
 */
export function fetchLatestSleepBySource(
  source: SleepSource,
): Promise<SleepSession | null> {
  return fetchJson<SleepSession | null>(
    `/sleep/latest?source=${encodeURIComponent(source)}`,
  );
}
