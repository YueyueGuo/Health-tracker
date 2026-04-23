import { fetchJson } from "./http";

export interface WakeEvent {
  type: "awake" | "out";
  duration_sec: number;
  offset_sec: number;
}

export interface SleepSession {
  id: number;
  source: string;
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
}

export function fetchSleepSessions(days = 30): Promise<SleepSession[]> {
  return fetchJson<SleepSession[]>(`/sleep?days=${days}`);
}

export function fetchSleepTrends(days = 30): Promise<SleepSession[]> {
  return fetchJson<SleepSession[]>(`/sleep/trends?days=${days}`);
}

export function fetchLatestSleep(): Promise<SleepSession | null> {
  return fetchJson<SleepSession | null>(`/sleep/latest`);
}
