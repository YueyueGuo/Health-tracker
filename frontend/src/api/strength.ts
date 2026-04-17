const BASE_URL = "/api";

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    throw new Error(`API error: ${resp.status} ${resp.statusText}`);
  }
  // 204 No Content has no body.
  if (resp.status === 204) return undefined as unknown as T;
  return resp.json();
}

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
  activity_id?: number | null;
}

// ── Fetchers ────────────────────────────────────────────────────────────────

export function fetchStrengthSessions(limit = 20): Promise<StrengthSession[]> {
  return fetchJson<StrengthSession[]>(`/strength/sessions?limit=${limit}`);
}

export function fetchStrengthSession(date: string): Promise<StrengthSessionDetail> {
  return fetchJson<StrengthSessionDetail>(`/strength/session/${date}`);
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
