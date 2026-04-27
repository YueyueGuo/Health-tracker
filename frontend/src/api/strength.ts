import { fetchJson, fetchOptionalJson } from "./http";

// ── Domain types ────────────────────────────────────────────────────────────

export interface StrengthSet {
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
}

export interface StrengthSessionCreate {
  date: string; // YYYY-MM-DD
  activity_id: number | null;
  sets: StrengthSetInput[];
}

export interface StrengthSetPatch {
  exercise_name?: string;
  set_number?: number;
  reps?: number;
  weight_kg?: number | null;
  rpe?: number | null;
  notes?: string | null;
  performed_at?: string | null;
  activity_id?: number | null;
}

// ── Fetchers ────────────────────────────────────────────────────────────────

export function fetchStrengthSessions(limit = 20): Promise<StrengthSession[]> {
  return fetchJson<StrengthSession[]>(`/strength/sessions?limit=${limit}`);
}

export function fetchStrengthSession(date: string): Promise<StrengthSessionDetail> {
  return fetchJson<StrengthSessionDetail>(`/strength/session/${date}`);
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

export function updateStrengthSet(
  id: number,
  patch: StrengthSetPatch
): Promise<StrengthSet> {
  return fetchJson<StrengthSet>(`/strength/sets/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteStrengthSet(id: number): Promise<void> {
  return fetchJson<void>(`/strength/sets/${id}`, { method: "DELETE" });
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
