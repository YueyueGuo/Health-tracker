/**
 * Typed fetchers for user-supplied feedback:
 *   - PATCH /api/activities/{id}/feedback  (RPE + notes on a workout)
 *   - POST  /api/insights/feedback         (thumbs up/down on a day's rec)
 */

import { fetchJson } from "./http";

interface ActivityFeedback {
  activity_id: number;
  rpe: number | null;
  user_notes: string | null;
  rated_at: string | null;
}

interface ActivityFeedbackPayload {
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

interface RecommendationFeedbackPayload {
  recommendation_date: string;
  cache_key?: string | null;
  vote: VoteValue;
  reason?: string | null;
}

interface RecommendationFeedback {
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

