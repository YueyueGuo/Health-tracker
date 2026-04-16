import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine,
} from "recharts";
import { useApi } from "../hooks/useApi";
import { fetchDashboardOverview } from "../api/client";

export default function TrainingLoad() {
  const { data, loading, error } = useApi(fetchDashboardOverview);

  if (loading) return <div className="loading">Loading training data...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!data?.training_load) return <div className="card">No training data available.</div>;

  const { ctl, atl, tsb, daily_load } = data.training_load;

  // Merge CTL, ATL, TSB into one chart dataset
  const fitnessData = ctl.map((c: any, i: number) => ({
    date: new Date(c.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    fitness: c.value,
    fatigue: atl[i]?.value,
    form: tsb[i]?.value,
  }));

  const loadData = daily_load.map((d: any) => ({
    date: new Date(d.date).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    load: d.value,
  }));

  return (
    <div>
      <div className="page-header">
        <h1>Training Load</h1>
        <p>Fitness, fatigue, and form tracking</p>
      </div>

      <div className="card">
        <h2>Fitness / Fatigue / Form</h2>
        <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 16 }}>
          CTL (42-day fitness) vs ATL (7-day fatigue). TSB = fitness minus fatigue (positive = fresh, negative = fatigued).
        </p>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={fitnessData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={11} interval="preserveStartEnd" />
            <YAxis stroke="var(--text-muted)" />
            <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }} />
            <Legend />
            <ReferenceLine y={0} stroke="var(--text-muted)" strokeDasharray="3 3" />
            <Line type="monotone" dataKey="fitness" stroke="#22c55e" strokeWidth={2} dot={false} name="Fitness (CTL)" />
            <Line type="monotone" dataKey="fatigue" stroke="#ef4444" strokeWidth={2} dot={false} name="Fatigue (ATL)" />
            <Line type="monotone" dataKey="form" stroke="#6366f1" strokeWidth={2} dot={false} name="Form (TSB)" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h2>Daily Training Load</h2>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={loadData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={11} interval="preserveStartEnd" />
            <YAxis stroke="var(--text-muted)" />
            <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }} />
            <Bar dataKey="load" fill="#6366f1" radius={[4, 4, 0, 0]} name="Training Load" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {data.weekly_stats && data.weekly_stats.length > 0 && (
        <div className="card">
          <h2>Weekly Volume</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th>Week</th>
                <th>Activities</th>
                <th>Distance</th>
                <th>Time</th>
                <th>Calories</th>
              </tr>
            </thead>
            <tbody>
              {data.weekly_stats.map((w: any) => (
                <tr key={w.week_start}>
                  <td>{w.week_start}</td>
                  <td>{w.total_activities}</td>
                  <td>{w.total_distance_km} km</td>
                  <td>{Math.floor(w.total_time_minutes / 60)}h {w.total_time_minutes % 60}m</td>
                  <td>{w.total_calories}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
