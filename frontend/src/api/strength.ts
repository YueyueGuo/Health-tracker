import { fetchJson, fetchOptionalJson } from "./http";

// ── Domain types ────────────────────────────────────────────────────────────

interface StrengthSet {
  id: number;
  activity_id: number | null;
  date: string; // YYYY-MM-DD
  exercise_name: string;
  set_number: number;
  reps: number;
  weight_kg: number | null;
  rpe: number | null;
  notes: string | null;
  /** Naive-local ISO datetime stamped when the set was logged.
   *  Optional only for legacy rows created before Live-only mode. */
  performed_at?: string | null;
  /** Working-HR window ending at ``performed_at`` (45s lookback).
   *  Populated on the session_summary response when the linked Strava
   *  activity's streams are cached. Undefined otherwise. */
  avg_hr?: number;
  max_hr?: number;
  /** Sets that share a non-null group id were performed back-to-back as a
   *  superset. Scoped to the session (date). Null = standalone. */
  superset_group_id?: number | null;
  /** Display order across the session (0-based). Lets the detail page
   *  render exercises in the recorded sequence rather than alphabetical. */
  order_index?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface StrengthSession {
  date: string;
  exercise_count: number;
  total_sets: number;
  total_volume_kg: number;
  activity_id: number | null;
}

export interface ExerciseBreakdown {
  name: string;
  sets: StrengthSet[];
  max_weight: number | null;
  total_volume: number;
  est_1rm: number | null;
  /** Modal `superset_group_id` across this exercise's sets, or null when
   *  the exercise was performed standalone. */
  superset_group_id?: number | null;
  /** 0-based position within the session, mirroring the recorded order. */
  order_index?: number | null;
}

export interface StrengthSessionDetail {
  date: string;
  activity_id: number | null;
  sets: StrengthSet[];
  exercises: ExerciseBreakdown[];
  /** Decimated [offset_sec, bpm] pairs spanning the linked Strava
   *  activity. Present only when the activity's time + heartrate streams
   *  are cached. */
  hr_curve?: Array<[number, number]>;
  /** ISO string of the linked activity's start_date_local (or UTC
   *  start_date fallback). Lets the frontend convert set performed_at
   *  timestamps to x-axis offsets for the hr_curve chart. */
  activity_start_iso?: string;
  /** Duration in seconds. Prefers ``ended_at - started_at`` when stamped
   *  by the recorder; otherwise derived from ``performed_at`` range. */
  duration_sec?: number | null;
  /** Total sets logged across all exercises in the session. */
  total_sets?: number;
  /** Total reps logged across all sets. */
  total_reps?: number;
  /** Total volume (sum of weight_kg × reps) across all weighted sets. */
  total_volume_kg?: number;
  /** Number of distinct exercises in the session. */
  exercise_count?: number;
  /** Naive-local ISO datetime stamped on the recorder's "Start" tap. */
  started_at?: string | null;
  /** Naive-local ISO datetime stamped on the recorder's "Finish" tap. */
  ended_at?: string | null;
}

export interface ProgressionPoint {
  date: string;
  max_weight_kg: number;
  est_1rm_kg: number;
  total_volume_kg: number;
  top_set_reps: number;
}

export interface StrengthSetInput {
  exercise_name: string;
  set_number: number;
  reps: number;
  weight_kg: number | null;
  rpe: number | null;
  notes: string | null;
  /** Naive-local ISO string (no tz) stamped by the "Log set" tap. */
  performed_at?: string | null;
  /** Superset grouping. Sets sharing a non-null id within a single
   *  session were performed back-to-back. */
  superset_group_id?: number | null;
  /** 0-based exercise ordering within the session. */
  order_index?: number | null;
}

interface StrengthSessionCreate {
  date: string; // YYYY-MM-DD
  activity_id: number | null;
  sets: StrengthSetInput[];
  /** Optional ISO timestamps stamped on Start / Finish taps. The backend
   *  denormalizes these onto each row of the session. */
  started_at?: string | null;
  ended_at?: string | null;
}

// ── Fetchers ────────────────────────────────────────────────────────────────

export function fetchStrengthSessions(limit = 20): Promise<StrengthSession[]> {
  return fetchJson<StrengthSession[]>(`/strength/sessions?limit=${limit}`);
}

export function fetchStrengthSessionOptional(
  date: string
): Promise<StrengthSessionDetail | null> {
  return fetchOptionalJson<StrengthSessionDetail>(`/strength/session/${date}`);
}

export function createStrengthSession(
  payload: StrengthSessionCreate
): Promise<{ created: number; session: StrengthSessionDetail | null }> {
  return fetchJson(`/strength/sets`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchStrengthProgression(
  exercise_name: string,
  days = 180
): Promise<ProgressionPoint[]> {
  return fetchJson<ProgressionPoint[]>(
    `/strength/progression/${encodeURIComponent(exercise_name)}?days=${days}`
  );
}

export function fetchStrengthExercises(q?: string): Promise<string[]> {
  const qs = q ? `?q=${encodeURIComponent(q)}` : "";
  return fetchJson<string[]>(`/strength/exercises${qs}`);
}
