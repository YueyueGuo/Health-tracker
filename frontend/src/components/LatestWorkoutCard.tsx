import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import { formatDistance, formatPace, useUnits } from "../hooks/useUnits";
import {
  fetchLatestWorkoutInsight,
  type WorkoutInsightResponse,
} from "../api/insights";
import ClassificationBadge from "./ClassificationBadge";
import type { ClassificationType } from "../api/client";

function formatDuration(seconds: number | null): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  }) + " · " + d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export default function LatestWorkoutCard() {
  const { units } = useUnits();
  const { data, loading, error, setData } = useApi(() => fetchLatestWorkoutInsight());
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      // Single round trip: refresh=true returns the fresh payload and
      // primes the backend cache in one call.
      const fresh = await fetchLatestWorkoutInsight({ refresh: true });
      setData(fresh);
    } finally {
      setRefreshing(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="card">
        <h2>Latest Workout</h2>
        <div className="loading" style={{ padding: 24 }}>Analyzing…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <h2>Latest Workout</h2>
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
          Couldn't load insight: {error}
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="card">
        <h2>Latest Workout</h2>
        <div style={{ color: "var(--text-muted)" }}>No completed activities yet.</div>
      </div>
    );
  }

  return (
    <LatestWorkoutCardView
      data={data}
      units={units}
      onRefresh={handleRefresh}
      refreshing={refreshing}
    />
  );
}

interface ViewProps {
  data: WorkoutInsightResponse;
  units: "imperial" | "metric";
  onRefresh: () => void;
  refreshing: boolean;
}

function LatestWorkoutCardView({ data, units, onRefresh, refreshing }: ViewProps) {
  const w = data.workout;
  const ins = data.insight;
  const isRun = w.sport_type.endsWith("Run");

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <h2>Latest Workout</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {data.cached ? "cached" : "fresh"} · {data.model}
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

      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <Link
          to={`/activities/${w.id}`}
          style={{ fontSize: 18, fontWeight: 600, color: "var(--text)" }}
        >
          {w.name}
        </Link>
        <ClassificationBadge
          type={w.classification_type as ClassificationType}
          flags={w.classification_flags}
        />
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {formatDate(w.start_date_local || w.start_date)}
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <Metric label="Distance" value={formatDistance(w.distance_m, units)} />
        <Metric label="Duration" value={formatDuration(w.moving_time_s)} />
        {isRun && (
          <Metric
            label="Pace"
            value={w.avg_speed_ms ? formatPace(w.avg_speed_ms, units) : "—"}
          />
        )}
        {!isRun && w.avg_power_w && (
          <Metric label="Avg Power" value={`${Math.round(w.avg_power_w)}W`} />
        )}
        <Metric label="Avg HR" value={w.avg_hr ? `${Math.round(w.avg_hr)}` : "—"} />
        {w.suffer_score != null && (
          <Metric label="Effort" value={String(w.suffer_score)} />
        )}
      </div>

      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{ins.headline}</div>
        <p style={{ lineHeight: 1.5, color: "var(--text)" }}>{ins.takeaway}</p>
      </div>

      {ins.vs_history && (
        <div
          style={{
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: "10px 14px",
            marginBottom: 12,
            fontSize: 13,
            color: "var(--text-muted)",
          }}
        >
          <span style={{ color: "var(--accent-light)", fontWeight: 600 }}>vs history: </span>
          {ins.vs_history}
          {w.historical_comparison?.pace_percentile != null && (
            <span style={{ marginLeft: 8, color: "var(--text)" }}>
              (pace pct: {w.historical_comparison.pace_percentile})
            </span>
          )}
        </div>
      )}

      {ins.notable_segments.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 6, letterSpacing: 0.5 }}>
            Notable
          </div>
          <ul style={{ paddingLeft: 18, lineHeight: 1.6, fontSize: 14 }}>
            {ins.notable_segments.map((s, i) => (
              <li key={i}>
                <strong>{s.label}:</strong> {s.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      {ins.flags.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {ins.flags.map((f) => (
            <span
              key={f}
              className="chip"
              style={{ fontSize: 11 }}
            >
              {f}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{value}</div>
    </div>
  );
}
