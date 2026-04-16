const BASE_URL = "/api";

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    throw new Error(`API error: ${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

// Activities
export function fetchActivities(params?: {
  sport_type?: string;
  days?: number;
  limit?: number;
}) {
  const qs = new URLSearchParams();
  if (params?.sport_type) qs.set("sport_type", params.sport_type);
  if (params?.days) qs.set("days", String(params.days));
  if (params?.limit) qs.set("limit", String(params.limit));
  const query = qs.toString();
  return fetchJson<any[]>(`/activities${query ? `?${query}` : ""}`);
}

export function fetchActivity(id: number) {
  return fetchJson<any>(`/activities/${id}`);
}

export function fetchSportTypes() {
  return fetchJson<string[]>("/activities/types");
}

// Sleep
export function fetchSleepSessions(days = 30) {
  return fetchJson<any[]>(`/sleep?days=${days}`);
}

export function fetchSleepTrends(days = 30) {
  return fetchJson<any[]>(`/sleep/trends?days=${days}`);
}

// Recovery
export function fetchRecovery(days = 30) {
  return fetchJson<any[]>(`/recovery?days=${days}`);
}

export function fetchRecoveryTrends(days = 30) {
  return fetchJson<any[]>(`/recovery/trends?days=${days}`);
}

// Dashboard
export function fetchDashboardOverview() {
  return fetchJson<any>("/dashboard/overview");
}

// Chat / Analysis
export function askQuestion(question: string, model?: string) {
  return fetchJson<{ answer: string; model: string; tokens_used: number | null }>(
    "/chat/ask",
    {
      method: "POST",
      body: JSON.stringify({ question, model: model || undefined }),
    }
  );
}

export function fetchDailyBriefing(model?: string) {
  const qs = model ? `?model=${model}` : "";
  return fetchJson<{ answer: string; model: string }>(`/chat/daily-briefing${qs}`);
}

export function fetchWorkoutAnalysis(activityId: number, model?: string) {
  const qs = model ? `?model=${model}` : "";
  return fetchJson<{ answer: string; model: string }>(`/chat/workout/${activityId}${qs}`);
}

export function fetchAvailableModels() {
  return fetchJson<{ models: string[] }>("/chat/models");
}

// Sync
export function triggerSync(source = "all") {
  return fetchJson<{ status: string; synced: Record<string, number> }>("/sync/trigger", {
    method: "POST",
    body: JSON.stringify({ source }),
  });
}

export function fetchSyncStatus() {
  return fetchJson<Record<string, any>>("/sync/status");
}
