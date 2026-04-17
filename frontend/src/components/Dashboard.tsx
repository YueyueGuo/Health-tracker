import { useApi } from "../hooks/useApi";
import { fetchDashboardOverview, triggerSync } from "../api/client";
import { useState } from "react";
import { useUnits } from "../hooks/useUnits";
import WeeklySummaryCards from "./WeeklySummaryCards";

export default function Dashboard() {
  const { units } = useUnits();
  const { data, loading, error, reload } = useApi(fetchDashboardOverview);
  const [syncing, setSyncing] = useState(false);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await triggerSync("all");
      await reload();
    } finally {
      setSyncing(false);
    }
  };

  if (loading) return <div className="loading">Loading dashboard...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!data) return null;

  const thisWeek = data.weekly_stats?.[0];
  const lastSleep = data.recent_sleep?.[data.recent_sleep.length - 1];
  const lastRecovery = data.recent_recovery?.[data.recent_recovery.length - 1];

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1>Dashboard</h1>
          <p>Your health & fitness overview</p>
        </div>
        <button className="btn" onClick={handleSync} disabled={syncing}>
          {syncing ? "Syncing..." : "Sync Data"}
        </button>
      </div>

      <div className="metric-grid">
        <div className="metric-card">
          <div className="label">Activities This Week</div>
          <div className="value">{thisWeek?.total_activities ?? "—"}</div>
          <div className="subtext">
            {thisWeek?.total_distance_km
              ? units === "imperial"
                ? `${(thisWeek.total_distance_km * 0.621371).toFixed(1)} mi`
                : `${thisWeek.total_distance_km} km`
              : "No data"}
          </div>
        </div>

        <div className="metric-card">
          <div className="label">Training Time</div>
          <div className="value">
            {thisWeek?.total_time_minutes
              ? `${Math.floor(thisWeek.total_time_minutes / 60)}h ${thisWeek.total_time_minutes % 60}m`
              : "—"}
          </div>
          <div className="subtext">
            {thisWeek?.total_calories ? `${thisWeek.total_calories} cal` : ""}
          </div>
        </div>

        <div className="metric-card">
          <div className="label">Last Sleep Score</div>
          <div className="value" style={{ color: getSleepColor(lastSleep?.sleep_score) }}>
            {lastSleep?.sleep_score != null ? Math.round(lastSleep.sleep_score) : "—"}
          </div>
          <div className="subtext">
            {lastSleep?.total_duration
              ? `${Math.floor(lastSleep.total_duration / 60)}h ${lastSleep.total_duration % 60}m`
              : "No data"}
          </div>
        </div>

        <div className="metric-card">
          <div className="label">Recovery</div>
          <div className="value" style={{ color: getRecoveryColor(lastRecovery?.recovery_score) }}>
            {lastRecovery?.recovery_score != null
              ? `${Math.round(lastRecovery.recovery_score)}%`
              : "—"}
          </div>
          <div className="subtext">
            {lastRecovery?.hrv ? `HRV: ${Math.round(lastRecovery.hrv)}ms` : "No data"}
          </div>
        </div>
      </div>

      <WeeklySummaryCards weeks={4} />

      {thisWeek?.sport_breakdown && Object.keys(thisWeek.sport_breakdown).length > 0 && (
        <div className="card">
          <h2>Sport Breakdown</h2>
          <div style={{ display: "flex", gap: 24 }}>
            {Object.entries(thisWeek.sport_breakdown).map(([sport, count]) => (
              <div key={sport}>
                <strong>{sport}</strong>: {count as number} session{(count as number) !== 1 ? "s" : ""}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function getSleepColor(score?: number | null): string {
  if (score == null) return "var(--text-muted)";
  if (score >= 80) return "var(--green)";
  if (score >= 60) return "var(--orange)";
  return "var(--red)";
}

function getRecoveryColor(score?: number | null): string {
  if (score == null) return "var(--text-muted)";
  if (score >= 67) return "var(--green)";
  if (score >= 34) return "var(--orange)";
  return "var(--red)";
}
