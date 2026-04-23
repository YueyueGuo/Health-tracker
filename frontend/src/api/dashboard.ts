import { fetchJson } from "./http";

export interface WeeklyStats {
  week_start: string;
  week_end: string;
  total_activities: number;
  total_distance_km: number;
  total_time_minutes: number;
  total_calories: number;
  sport_breakdown: Record<string, number>;
}

export interface MetricPoint {
  date: string;
  value: number;
}

export interface TrainingLoad {
  ctl: MetricPoint[];
  atl: MetricPoint[];
  tsb: MetricPoint[];
  daily_load: MetricPoint[];
}

export interface SleepTrend {
  date: string;
  source: string;
  sleep_score: number | null;
  total_duration: number | null;
  deep_sleep: number | null;
  rem_sleep: number | null;
  light_sleep: number | null;
  awake_time: number | null;
  hrv: number | null;
  avg_hr: number | null;
  respiratory_rate: number | null;
}

export interface RecoveryTrend {
  date: string;
  recovery_score: number | null;
  resting_hr: number | null;
  hrv: number | null;
  spo2: number | null;
  strain_score: number | null;
}

export interface DashboardOverview {
  weekly_stats: WeeklyStats[];
  recent_sleep: SleepTrend[];
  recent_recovery: RecoveryTrend[];
  training_load: TrainingLoad;
}

export function fetchDashboardOverview() {
  return fetchJson<DashboardOverview>("/dashboard/overview");
}
