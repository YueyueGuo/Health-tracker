/**
 * Typed fetchers for the /api/goals surface.
 */

const BASE_URL = "/api";

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = "";
    try {
      const body = await resp.json();
      if (body && typeof body === "object" && "detail" in body) {
        detail = String((body as { detail?: unknown }).detail ?? "");
      }
    } catch {
      // not JSON
    }
    throw new Error(detail || `API error: ${resp.status} ${resp.statusText}`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export type GoalStatus = "active" | "completed" | "abandoned";

export interface Goal {
  id: number;
  race_type: string;
  description: string | null;
  target_date: string; // ISO date
  is_primary: boolean;
  status: GoalStatus;
}

export interface CreateGoalPayload {
  race_type: string;
  description?: string | null;
  target_date: string;
  is_primary?: boolean;
  status?: GoalStatus;
}

export interface PatchGoalPayload {
  race_type?: string;
  description?: string | null;
  target_date?: string;
  is_primary?: boolean;
  status?: GoalStatus;
}

export function listGoals() {
  return fetchJson<Goal[]>("/goals");
}

export function createGoal(payload: CreateGoalPayload) {
  return fetchJson<Goal>("/goals", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function patchGoal(id: number, payload: PatchGoalPayload) {
  return fetchJson<Goal>(`/goals/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteGoal(id: number) {
  return fetchJson<void>(`/goals/${id}`, { method: "DELETE" });
}

export function setPrimaryGoal(id: number) {
  return fetchJson<Goal>(`/goals/${id}/set-primary`, { method: "POST" });
}
