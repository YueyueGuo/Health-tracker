import { useEffect, useState } from "react";
import {
  getFeedbackStats,
  postRecommendationFeedback,
  type VoteValue,
} from "../api/feedback";

interface Props {
  recommendationDate: string;
  cacheKey: string;
}

/**
 * Thumbs up / down on the daily recommendation. A down-vote opens an
 * inline "tell us why" textarea so the LLM can see *why* past
 * recommendations were rejected on future runs (feedback_summary
 * snapshot → system prompt).
 *
 * Vote is keyed by ``recommendation_date`` on the backend so re-rating
 * the same day updates in place instead of stacking.
 */
export default function ThumbsFeedback({ recommendationDate, cacheKey }: Props) {
  const [vote, setVote] = useState<VoteValue | null>(null);
  const [reason, setReason] = useState("");
  const [showReason, setShowReason] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pre-load today's existing vote if one was already recorded.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const stats = await getFeedbackStats(7);
        if (cancelled) return;
        const today = stats.recent.find(
          (r) => r.recommendation_date === recommendationDate
        );
        if (today) {
          setVote(today.vote);
          setReason(today.reason ?? "");
          setSaved(true);
        }
      } catch {
        // stats lookup is best-effort; UI remains usable
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [recommendationDate]);

  const submit = async (nextVote: VoteValue, nextReason: string | null) => {
    setSaving(true);
    setError(null);
    try {
      await postRecommendationFeedback({
        recommendation_date: recommendationDate,
        cache_key: cacheKey,
        vote: nextVote,
        reason: nextReason,
      });
      setVote(nextVote);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const onThumbsUp = async () => {
    setShowReason(false);
    await submit("up", null);
  };

  const onThumbsDown = async () => {
    setShowReason(true);
    // Record the down-vote immediately; reason is an optional follow-up.
    await submit("down", reason.trim() ? reason.trim() : null);
  };

  const saveReason = async () => {
    if (!vote) return;
    await submit(vote, reason.trim() ? reason.trim() : null);
  };

  return (
    <div style={{ marginTop: 12 }}>
      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "center",
          fontSize: 12,
        }}
      >
        <span style={{ color: "var(--text-muted)" }}>
          Was this useful?
        </span>
        <button
          type="button"
          className={vote === "up" ? "btn" : "btn btn-ghost"}
          disabled={saving}
          onClick={onThumbsUp}
          style={{ padding: "4px 10px", fontSize: 14 }}
          aria-label="thumbs up"
        >
          {"\u{1F44D}"}
        </button>
        <button
          type="button"
          className={vote === "down" ? "btn" : "btn btn-ghost"}
          disabled={saving}
          onClick={onThumbsDown}
          style={{ padding: "4px 10px", fontSize: 14 }}
          aria-label="thumbs down"
        >
          {"\u{1F44E}"}
        </button>
        {saved && !saving && (
          <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
            Thanks — recorded.
          </span>
        )}
        {saving && (
          <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
            Saving…
          </span>
        )}
      </div>

      {(showReason || (vote === "down" && saved)) && (
        <div style={{ marginTop: 8 }}>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why didn't this land? (optional — e.g. 'too hard, legs wrecked', 'wrong sport today')"
            rows={2}
            style={{
              width: "100%",
              padding: 8,
              boxSizing: "border-box",
              fontSize: 12,
            }}
          />
          <button
            type="button"
            className="btn btn-ghost"
            disabled={saving}
            onClick={saveReason}
            style={{ padding: "4px 10px", fontSize: 12, marginTop: 4 }}
          >
            Save reason
          </button>
        </div>
      )}

      {error && (
        <div className="error" style={{ marginTop: 6, fontSize: 12 }}>
          {error}
        </div>
      )}
    </div>
  );
}
