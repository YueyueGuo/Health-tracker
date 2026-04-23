import { useState } from "react";
import { useApi } from "../hooks/useApi";
import {
  fetchDailyRecommendation,
  type DailyRecommendationResponse,
  type Intensity,
} from "../api/insights";
import ThumbsFeedback from "./ThumbsFeedback";

const INTENSITY_COLOR: Record<Intensity, string> = {
  rest: "#8b8fa3",
  recovery: "#22c55e",
  easy: "#60a5fa",
  moderate: "#f59e0b",
  quality: "#ef4444",
};

const INTENSITY_LABEL: Record<Intensity, string> = {
  rest: "Rest",
  recovery: "Recovery",
  easy: "Easy",
  moderate: "Moderate",
  quality: "Quality",
};

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function RecommendationCard() {
  const { data, loading, error, setData } = useApi(() => fetchDailyRecommendation(false));
  const [refreshing, setRefreshing] = useState(false);
  const [showInputs, setShowInputs] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      // Single round trip: the refresh=true call itself returns the fresh
      // payload AND primes the backend cache for subsequent page loads.
      const fresh = await fetchDailyRecommendation(true);
      setData(fresh);
    } finally {
      setRefreshing(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="card" style={{ minHeight: 200 }}>
        <h2>Today's Recommendation</h2>
        <div className="loading" style={{ padding: 24 }}>Thinking…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card" style={{ minHeight: 200 }}>
        <h2>Today's Recommendation</h2>
        <div style={{ color: "var(--text-muted)", padding: 16 }}>
          <p style={{ marginBottom: 8 }}>Couldn't generate a recommendation.</p>
          <p style={{ fontSize: 12 }}>{error}</p>
          <p style={{ fontSize: 12, marginTop: 12 }}>
            Make sure one of <code>ANTHROPIC_API_KEY</code>, <code>OPENAI_API_KEY</code>,
            or <code>GOOGLE_AI_API_KEY</code> is set in <code>.env</code>.
          </p>
          <button className="btn" onClick={handleRefresh} disabled={refreshing} style={{ marginTop: 12 }}>
            {refreshing ? "Retrying..." : "Retry"}
          </button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  return (
    <RecommendationCardView
      data={data}
      onRefresh={handleRefresh}
      refreshing={refreshing}
      showInputs={showInputs}
      onToggleInputs={() => setShowInputs((v) => !v)}
    />
  );
}

interface ViewProps {
  data: DailyRecommendationResponse;
  onRefresh: () => void;
  refreshing: boolean;
  showInputs: boolean;
  onToggleInputs: () => void;
}

function RecommendationCardView({
  data,
  onRefresh,
  refreshing,
  showInputs,
  onToggleInputs,
}: ViewProps) {
  const rec = data.recommendation;
  const tl = data.inputs.training_load;
  const sleep = data.inputs.sleep;
  const recovery = data.inputs.recovery;
  const color = INTENSITY_COLOR[rec.intensity] ?? "var(--accent)";

  return (
    <div className="card" style={{ minHeight: 200 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <h2>Today's Recommendation</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {data.cached ? `cached, ${timeAgo(data.generated_at)}` : "fresh"}
            {" · "}
            {data.model}
          </span>
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="btn"
            style={{ padding: "4px 10px", fontSize: 12 }}
          >
            {refreshing ? "…" : "Refresh"}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "center", marginBottom: 16 }}>
        <span
          style={{
            background: color,
            color: rec.intensity === "moderate" || rec.intensity === "rest" ? "#000" : "#fff",
            padding: "6px 14px",
            borderRadius: 999,
            fontSize: 13,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: 0.5,
          }}
        >
          {INTENSITY_LABEL[rec.intensity] ?? rec.intensity}
        </span>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          confidence: <strong style={{ color: "var(--text)" }}>{rec.confidence}</strong>
        </span>
      </div>

      <p style={{ fontSize: 18, lineHeight: 1.5, marginBottom: 16 }}>{rec.suggestion}</p>

      {rec.rationale.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 8, letterSpacing: 0.5 }}>
            Why
          </div>
          <ul style={{ paddingLeft: 18, lineHeight: 1.6, fontSize: 14 }}>
            {rec.rationale.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {rec.concerns.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: "var(--orange)", textTransform: "uppercase", marginBottom: 8, letterSpacing: 0.5 }}>
            Watch out
          </div>
          <ul style={{ paddingLeft: 18, lineHeight: 1.6, fontSize: 14, color: "var(--text-muted)" }}>
            {rec.concerns.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      <ThumbsFeedback
        recommendationDate={data.recommendation_date}
        cacheKey={data.cache_key}
      />

      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12, marginTop: 12 }}>
        <button
          onClick={onToggleInputs}
          style={{
            background: "transparent",
            border: "none",
            color: "var(--text-muted)",
            fontSize: 12,
            cursor: "pointer",
            padding: 0,
          }}
        >
          {showInputs ? "Hide inputs" : "Show inputs"}
        </button>
        {showInputs && (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
            gap: 12,
            marginTop: 12,
            fontSize: 12,
          }}>
            <InputCell
              label="ACWR (7d/28d)"
              value={tl.acwr != null ? tl.acwr.toFixed(2) : "—"}
              hint={acwrHint(tl.acwr)}
            />
            <InputCell
              label="Monotony"
              value={tl.monotony != null ? tl.monotony.toFixed(2) : "—"}
              hint={tl.monotony != null && tl.monotony > 2 ? "high" : undefined}
            />
            <InputCell
              label="Days since hard"
              value={tl.days_since_hard != null ? String(tl.days_since_hard) : "—"}
            />
            <InputCell
              label="Sleep debt"
              value={sleep.sleep_debt_min != null ? `${Math.round(sleep.sleep_debt_min / 60 * 10) / 10}h` : "—"}
            />
            <InputCell
              label="Last HRV"
              value={sleep.last_night_hrv != null ? `${Math.round(sleep.last_night_hrv)}ms` : "—"}
            />
            <InputCell
              label="Recovery"
              value={recovery.today_score != null ? `${Math.round(recovery.today_score)}%` : "—"}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function InputCell({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div style={{
      background: "var(--bg)",
      borderRadius: 8,
      padding: "10px 12px",
      border: "1px solid var(--border)",
    }}>
      <div style={{ color: "var(--text-muted)", marginBottom: 2, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.3 }}>
        {label}
      </div>
      <div style={{ fontSize: 16, fontWeight: 600 }}>{value}</div>
      {hint && <div style={{ fontSize: 10, color: "var(--orange)", marginTop: 2 }}>{hint}</div>}
    </div>
  );
}

function acwrHint(acwr: number | null): string | undefined {
  if (acwr == null) return undefined;
  if (acwr > 1.5) return "spike";
  if (acwr > 1.3) return "high";
  if (acwr < 0.8) return "low";
  return undefined;
}
