import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useState } from "react";
import { useApi } from "../hooks/useApi";
import { fetchRecoveryTrends } from "../api/recovery";

export default function RecoveryPanel() {
  const [days, setDays] = useState(30);
  const { data, loading, error } = useApi(() => fetchRecoveryTrends(days), [days]);

  if (loading) return <div className="loading">Loading recovery data...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!data || data.length === 0) {
    return (
      <div>
        <div className="page-header">
          <h1>Recovery</h1>
          <p>No recovery data available. Connect Whoop to get started.</p>
        </div>
      </div>
    );
  }

  const chartData = data.map((r) => ({
    date: new Date(r.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    recovery: r.recovery_score,
    hrv: r.hrv,
    restingHr: r.resting_hr,
    strain: r.strain_score,
  }));

  const latestRecovery = data[data.length - 1];

  return (
    <div>
      <div className="page-header">
        <h1>Recovery</h1>
        <p>Recovery scores, HRV, and strain tracking</p>
      </div>

      <div className="filter-bar">
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div className="metric-grid">
        <div className="metric-card">
          <div className="label">Latest Recovery</div>
          <div className="value" style={{ color: getColor(latestRecovery?.recovery_score) }}>
            {latestRecovery?.recovery_score != null ? `${Math.round(latestRecovery.recovery_score)}%` : "—"}
          </div>
        </div>
        <div className="metric-card">
          <div className="label">Latest HRV</div>
          <div className="value">{latestRecovery?.hrv ? `${Math.round(latestRecovery.hrv)}ms` : "—"}</div>
        </div>
        <div className="metric-card">
          <div className="label">Resting HR</div>
          <div className="value">
            {latestRecovery?.resting_hr ? `${Math.round(latestRecovery.resting_hr)} bpm` : "—"}
          </div>
        </div>
        <div className="metric-card">
          <div className="label">Strain</div>
          <div className="value">{latestRecovery?.strain_score?.toFixed(1) ?? "—"}</div>
        </div>
      </div>

      <div className="card">
        <h2>Recovery Score</h2>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={12} />
            <YAxis domain={[0, 100]} stroke="var(--text-muted)" />
            <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }} />
            <Line type="monotone" dataKey="recovery" stroke="#22c55e" strokeWidth={2} dot={{ r: 3 }} name="Recovery %" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h2>HRV & Resting HR</h2>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={12} />
            <YAxis yAxisId="hrv" stroke="#6366f1" />
            <YAxis yAxisId="hr" orientation="right" stroke="#ef4444" />
            <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }} />
            <Legend />
            <Line yAxisId="hrv" type="monotone" dataKey="hrv" stroke="#6366f1" strokeWidth={2} name="HRV (ms)" />
            <Line yAxisId="hr" type="monotone" dataKey="restingHr" stroke="#ef4444" strokeWidth={2} name="Resting HR (bpm)" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function getColor(score?: number | null): string {
  if (score == null) return "var(--text-muted)";
  if (score >= 67) return "var(--green)";
  if (score >= 34) return "var(--orange)";
  return "var(--red)";
}
