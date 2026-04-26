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

export interface SleepTodayPayload {
  last_night_score: number | null;
  last_night_duration_min: number | null;
  last_night_deep_min: number | null;
  last_night_rem_min: number | null;
  last_night_date: string | null;
}

export interface RecoveryTodayPayload {
  today_hrv: number | null;
  today_resting_hr: number | null;
  hrv_baseline_7d: number | null;
  hrv_trend: "up" | "down" | "flat" | null;
  hrv_source: "eight_sleep" | "whoop" | null;
}

export interface TrainingTodayPayload {
  yesterday_stress: number;
  week_to_date_load: number;
  acwr: number | null;
  acwr_band: "detraining" | "optimal" | "caution" | "elevated" | null;
  days_since_hard: number | null;
}

export interface EnvironmentForecastPayload {
  temp_c: number | null;
  high_c: number | null;
  low_c: number | null;
  conditions: string | null;
  wind_ms: number | null;
}

export interface EnvironmentPollenPayload {
  alder: number | null;
  birch: number | null;
  grass: number | null;
  mugwort: number | null;
  olive: number | null;
  ragweed: number | null;
}

export interface EnvironmentAirQualityPayload {
  us_aqi: number | null;
  european_aqi: number | null;
  pollen: EnvironmentPollenPayload | null;
}

export interface EnvironmentTodayPayload {
  forecast: EnvironmentForecastPayload | null;
  air_quality: EnvironmentAirQualityPayload | null;
}

export interface DashboardToday {
  as_of: string;
  sleep: SleepTodayPayload;
  recovery: RecoveryTodayPayload;
  training: TrainingTodayPayload;
  environment: EnvironmentTodayPayload | null;
}

export const ACWR_TOOLTIP =
  "Acute:Chronic Workload Ratio -- last 7 days of training load divided by " +
  "last 28 days. >1.5 elevated injury risk; 0.8-1.3 optimal; <0.8 detraining.";

export function fetchDashboardToday() {
  return fetchJson<DashboardToday>("/dashboard/today");
}
