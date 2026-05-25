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
  /** Working-HR window from the linked device workout's HR stream.
   *  Populated by the auto-segmenter on the session_summary response when
   *  a device workout is linked. Undefined when no link / no HR data. */
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

export type LinkSource = "strava" | "apple_health";

export type SegmentationStatus =
  | "ok"
  | "too_few"
  | "too_many"
  | "flat"
  | "no_stream"
  | "no_curve"
  | "pending"
  | "error";

export interface StrengthSession {
  date: string;
  exercise_count: number;
  total_sets: number;
  total_volume_kg: number;
  activity_id: number | null;
  /** True when a device workout is linked to this session and HR data
   *  is potentially available (regardless of segmentation status). */
  hr_linked?: boolean;
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

export interface StrengthSessionLink {
  source: LinkSource;
  ref_id: number;
  name: string | null;
  sport: string | null;
  start_iso: string | null;
  duration_s: number | null;
  avg_hr: number | null;
  max_hr: number | null;
}

export interface StrengthSessionSegmentation {
  status: SegmentationStatus;
  detected_count: number;
  target_count: number;
}

export interface StrengthSegmentMarker {
  /** Session-wide chronological ordinal (1..N over all detected sets). */
  set_number: number;
  exercise_name?: string | null;
  per_exercise_set_number?: number | null;
  start_sec: number;
  end_sec: number;
}

export interface StrengthSessionDetail {
  date: string;
  /** Back-compat for legacy callers — populated when the link is a
   *  Strava activity. New consumers should read `link` instead. */
  activity_id: number | null;
  sets: StrengthSet[];
  exercises: ExerciseBreakdown[];
  /** Linked device workout, or null when this session has no link. */
  link: StrengthSessionLink | null;
  /** Segmentation result of the HR stream against the logged set count.
   *  Null when no link exists. */
  segmentation: StrengthSessionSegmentation | null;
  /** Decimated [offset_sec, bpm] pairs spanning the linked device
   *  workout. Null when no stream is available (e.g. Apple Health
   *  summary-only) or when streams haven't been fetched yet. */
  hr_curve: Array<[number, number]> | null;
  /** Detected per-set HR windows on the session-wide curve, used to
   *  overlay shaded bands. Null when segmentation produced no segments. */
  segment_markers: StrengthSegmentMarker[] | null;
  /** ISO string of the linked workout's local start. Null when no link. */
  activity_start_iso: string | null;
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

export interface LinkCandidate {
  source: LinkSource;
  ref_id: number;
  name: string | null;
  sport: string | null;
  start_local: string | null;
  duration_s: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  distance_m: number | null;
  hr_stream_available: boolean;
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

export interface LinkWorkoutBody {
  source: LinkSource;
  ref_id: number;
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

// ── Link / candidate / segmentation fetchers ────────────────────────────────

export function fetchLinkCandidates(date: string): Promise<LinkCandidate[]> {
  return fetchJson<LinkCandidate[]>(
    `/strength/session/${date}/link-candidates`
  );
}

export function linkWorkout(
  date: string,
  body: LinkWorkoutBody
): Promise<StrengthSessionDetail> {
  return fetchJson<StrengthSessionDetail>(`/strength/session/${date}/link`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function unlinkWorkout(date: string): Promise<void> {
  return fetchJson<void>(`/strength/session/${date}/link`, {
    method: "DELETE",
  });
}

export function resegmentSession(
  date: string
): Promise<StrengthSessionDetail> {
  return fetchJson<StrengthSessionDetail>(
    `/strength/session/${date}/resegment`,
    { method: "POST" }
  );
}
