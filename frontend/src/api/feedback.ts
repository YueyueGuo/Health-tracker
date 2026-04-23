/**
 * Typed fetchers for user-supplied feedback:
 *   - PATCH /api/activities/{id}/feedback  (RPE + notes on a workout)
 *   - POST  /api/insights/feedback         (thumbs up/down on a day's rec)
 *   - GET   /api/insights/feedback/stats   (aggregate)
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

export interface ActivityFeedback {
  activity_id: number;
  rpe: number | null;
  user_notes: string | null;
  rated_at: string | null;
}

export interface ActivityFeedbackPayload {
  rpe?: number | null;
  user_notes?: string | null;
}

export function patchActivityFeedback(
  activityId: number,
  payload: ActivityFeedbackPayload
) {
  return fetchJson<ActivityFeedback>(`/activities/${activityId}/feedback`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export type VoteValue = "up" | "down";

export interface RecommendationFeedbackPayload {
  recommendation_date: string;
  cache_key?: string | null;
  vote: VoteValue;
  reason?: string | null;
}

export interface RecommendationFeedback {
  id: number;
  recommendation_date: string;
  vote: VoteValue;
  reason: string | null;
  cache_key: string | null;
}

export function postRecommendationFeedback(
  payload: RecommendationFeedbackPayload
) {
  return fetchJson<RecommendationFeedback>("/insights/feedback", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface FeedbackStats {
  up: number;
  down: number;
  total: number;
  window_days: number;
  recent: Array<{
    recommendation_date: string;
    vote: VoteValue;
    reason: string | null;
  }>;
}

export function getFeedbackStats(days = 30) {
  return fetchJson<FeedbackStats>(`/insights/feedback/stats?days=${days}`);
}
