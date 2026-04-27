import { useState } from "react";
import { Sparkles, ThumbsUp, ThumbsDown, RefreshCw } from "lucide-react";
import { Card } from "../ui/Card";
import { useApi } from "../../hooks/useApi";
import { fetchDailyRecommendation } from "../../api/insights";
import {
  postRecommendationFeedback,
  type VoteValue,
} from "../../api/feedback";

export function RecommendationCardV2() {
  const { data, loading, error, setData } = useApi(() =>
    fetchDailyRecommendation(false)
  );
  const [refreshing, setRefreshing] = useState(false);
  const [vote, setVote] = useState<VoteValue | null>(null);
  const [voteSaving, setVoteSaving] = useState<VoteValue | null>(null);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const fresh = await fetchDailyRecommendation(true);
      setData(fresh);
      setVote(null);
    } finally {
      setRefreshing(false);
    }
  };

  const handleVote = async (next: VoteValue) => {
    if (!data) return;
    setVoteSaving(next);
    try {
      await postRecommendationFeedback({
        recommendation_date: data.recommendation_date,
        cache_key: data.cache_key,
        vote: next,
      });
      setVote(next);
    } finally {
      setVoteSaving(null);
    }
  };

  return (
    <Card className="relative overflow-hidden p-4 group">
      <div className="absolute inset-0 bg-shimmer animate-shimmer opacity-50 pointer-events-none" />
      <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-brand-green to-transparent opacity-50" />

      <div className="relative z-10">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-1.5">
            <Sparkles size={14} className="text-brand-green" />
            <span className="text-[10px] text-slate-400 uppercase tracking-wider font-medium">
              AI Coach
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <div>
            {loading && !data ? (
              <p className="text-sm text-slate-400">Thinking…</p>
            ) : error && !data ? (
              <p className="text-xs text-slate-400 leading-relaxed">
                Couldn't generate a recommendation. {error}
              </p>
            ) : data ? (
              <>
                <h4 className="text-xs font-bold text-white mb-1 leading-relaxed">
                  {data.recommendation.suggestion}
                </h4>
                {data.recommendation.rationale.length > 0 && (
                  <p className="text-xs text-slate-400 leading-relaxed max-w-md">
                    {data.recommendation.rationale.join(" ")}
                  </p>
                )}
                {data.recommendation.concerns.length > 0 && (
                  <p className="text-xs text-brand-amber/80 leading-relaxed max-w-md mt-2">
                    {data.recommendation.concerns.join(" ")}
                  </p>
                )}
              </>
            ) : null}
          </div>

          <div className="flex items-center gap-2 mt-1">
            <button
              type="button"
              onClick={() => handleVote("up")}
              disabled={!data || voteSaving !== null}
              aria-label="Thumbs up"
              className={`p-2.5 rounded-lg transition-colors ${
                vote === "up"
                  ? "bg-brand-green/20 text-brand-green"
                  : "bg-cardBorder/50 hover:bg-cardBorder text-slate-300"
              } disabled:opacity-50`}
            >
              <ThumbsUp size={16} />
            </button>
            <button
              type="button"
              onClick={() => handleVote("down")}
              disabled={!data || voteSaving !== null}
              aria-label="Thumbs down"
              className={`p-2.5 rounded-lg transition-colors ${
                vote === "down"
                  ? "bg-brand-red/20 text-brand-red"
                  : "bg-cardBorder/50 hover:bg-cardBorder text-slate-300"
              } disabled:opacity-50`}
            >
              <ThumbsDown size={16} />
            </button>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={refreshing || loading}
              className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg bg-cardBorder/50 hover:bg-cardBorder transition-colors text-slate-300 text-xs font-semibold disabled:opacity-50"
            >
              <RefreshCw
                size={14}
                className={refreshing ? "animate-spin" : ""}
              />
              {refreshing ? "Generating…" : "Try something else"}
            </button>
          </div>
        </div>
      </div>
    </Card>
  );
}
