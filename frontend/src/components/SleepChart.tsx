import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  Legend,
} from "recharts";
import { useState } from "react";
import { useApi } from "../hooks/useApi";
import { fetchSleepTrends } from "../api/client";

export default function SleepChart() {
  const [days, setDays] = useState(30);
  const { data, loading, error } = useApi(() => fetchSleepTrends(days), [days]);

  if (loading) return <div className="loading">Loading sleep data...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!data || data.length === 0) {
    return (
      <div>
        <div className="page-header">
          <h1>Sleep</h1>
          <p>No sleep data available. Connect Eight Sleep or Whoop to get started.</p>
        </div>
      </div>
    );
  }

  const chartData = data.map((s: any) => ({
    date: new Date(s.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    score: s.sleep_score,
    total: s.total_duration ? Math.round(s.total_duration / 60 * 10) / 10 : null,
    deep: s.deep_sleep,
    rem: s.rem_sleep,
    light: s.light_sleep,
    hrv: s.hrv,
    avgHr: s.avg_hr,
  }));

  return (
    <div>
      <div className="page-header">
        <h1>Sleep</h1>
        <p>Sleep quality and trends</p>
      </div>

      <div className="filter-bar">
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div className="card">
        <h2>Sleep Score</h2>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={12} />
            <YAxis domain={[0, 100]} stroke="var(--text-muted)" />
            <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }} />
            <Line type="monotone" dataKey="score" stroke="#6366f1" strokeWidth={2} dot={{ r: 3 }} name="Sleep Score" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h2>Sleep Stages (minutes)</h2>
        <ResponsiveContainer width="100%" height={250}>
          <AreaChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={12} />
            <YAxis stroke="var(--text-muted)" />
            <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }} />
            <Legend />
            <Area type="monotone" dataKey="deep" stackId="1" stroke="#1e3a8a" fill="#1e3a8a" name="Deep" />
            <Area type="monotone" dataKey="rem" stackId="1" stroke="#14b8a6" fill="#14b8a6" name="REM" />
            <Area type="monotone" dataKey="light" stackId="1" stroke="#d4a574" fill="#d4a574" name="Light" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {chartData.some((d: any) => d.hrv != null) && (
        <div className="card">
          <h2>HRV Trend</h2>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={12} />
              <YAxis stroke="var(--text-muted)" />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }} />
              <Line type="monotone" dataKey="hrv" stroke="#22c55e" strokeWidth={2} dot={{ r: 3 }} name="HRV (ms)" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
