import { useParams } from "react-router-dom";
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
import { useApi } from "../hooks/useApi";
import { fetchActivity, fetchWorkoutAnalysis } from "../api/client";
import { useState } from "react";

export default function ActivityDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: activity, loading, error } = useApi(
    () => fetchActivity(Number(id)),
    [id]
  );
  const [analysis, setAnalysis] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      const result = await fetchWorkoutAnalysis(Number(id));
      setAnalysis(result.answer);
    } catch (e: any) {
      setAnalysis(`Error: ${e.message}`);
    } finally {
      setAnalyzing(false);
    }
  };

  if (loading) return <div className="loading">Loading activity...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!activity) return null;

  const streams = activity.streams || {};
  const hasHR = streams.heartrate?.length > 0;
  const hasPace = streams.velocity_smooth?.length > 0;
  const hasAltitude = streams.altitude?.length > 0;
  const timeData = streams.time || [];

  // Build chart data from streams
  const chartData = timeData.map((t: number, i: number) => ({
    time: Math.round(t / 60), // minutes
    hr: streams.heartrate?.[i],
    speed: streams.velocity_smooth?.[i]
      ? (1000 / streams.velocity_smooth[i] / 60) // min/km pace
      : undefined,
    altitude: streams.altitude?.[i],
  }));

  return (
    <div>
      <div className="page-header">
        <h1>{activity.name}</h1>
        <p>
          {activity.sport_type} &middot;{" "}
          {new Date(activity.start_date_local || activity.start_date).toLocaleDateString("en-US", {
            weekday: "long",
            month: "long",
            day: "numeric",
            year: "numeric",
          })}
        </p>
      </div>

      <div className="metric-grid">
        {activity.distance && (
          <div className="metric-card">
            <div className="label">Distance</div>
            <div className="value">{(activity.distance / 1000).toFixed(2)} km</div>
          </div>
        )}
        <div className="metric-card">
          <div className="label">Duration</div>
          <div className="value">{formatDuration(activity.moving_time)}</div>
          {activity.elapsed_time !== activity.moving_time && (
            <div className="subtext">Elapsed: {formatDuration(activity.elapsed_time)}</div>
          )}
        </div>
        {activity.average_hr && (
          <div className="metric-card">
            <div className="label">Avg HR</div>
            <div className="value">{Math.round(activity.average_hr)} bpm</div>
            {activity.max_hr && <div className="subtext">Max: {Math.round(activity.max_hr)} bpm</div>}
          </div>
        )}
        {activity.average_speed && activity.distance && (
          <div className="metric-card">
            <div className="label">Avg Pace</div>
            <div className="value">{formatPace(activity.average_speed)}</div>
          </div>
        )}
        {activity.average_power && (
          <div className="metric-card">
            <div className="label">Avg Power</div>
            <div className="value">{Math.round(activity.average_power)} W</div>
          </div>
        )}
        {activity.total_elevation && (
          <div className="metric-card">
            <div className="label">Elevation</div>
            <div className="value">{Math.round(activity.total_elevation)} m</div>
          </div>
        )}
        {activity.calories && (
          <div className="metric-card">
            <div className="label">Calories</div>
            <div className="value">{Math.round(activity.calories)}</div>
          </div>
        )}
      </div>

      {activity.weather && (
        <div className="card">
          <h2>Weather</h2>
          <div style={{ display: "flex", gap: 32 }}>
            <div>
              <strong>{activity.weather.temp_c}°C</strong> (feels like {activity.weather.feels_like_c}°C)
            </div>
            <div>{activity.weather.conditions} — {activity.weather.description}</div>
            <div>Humidity: {activity.weather.humidity}%</div>
            <div>Wind: {activity.weather.wind_speed} m/s</div>
          </div>
        </div>
      )}

      {chartData.length > 0 && (hasHR || hasPace || hasAltitude) && (
        <div className="card">
          <h2>Performance Data</h2>
          <ResponsiveContainer width="100%" height={350}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="time"
                label={{ value: "Minutes", position: "insideBottom", offset: -5, fill: "var(--text-muted)" }}
                stroke="var(--text-muted)"
              />
              {hasHR && (
                <YAxis yAxisId="hr" orientation="left" stroke="#ef4444" domain={["auto", "auto"]} />
              )}
              {hasPace && (
                <YAxis yAxisId="pace" orientation="right" stroke="#6366f1" reversed domain={["auto", "auto"]} />
              )}
              <Tooltip
                contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
              />
              <Legend />
              {hasHR && (
                <Line yAxisId="hr" type="monotone" dataKey="hr" stroke="#ef4444" dot={false} name="Heart Rate (bpm)" />
              )}
              {hasPace && (
                <Line yAxisId="pace" type="monotone" dataKey="speed" stroke="#6366f1" dot={false} name="Pace (min/km)" />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card">
        <h2>AI Analysis</h2>
        {!analysis && (
          <button className="btn" onClick={handleAnalyze} disabled={analyzing}>
            {analyzing ? "Analyzing..." : "Analyze This Workout"}
          </button>
        )}
        {analysis && (
          <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.7 }}>{analysis}</div>
        )}
      </div>
    </div>
  );
}

function formatDuration(seconds?: number): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`;
}

function formatPace(speedMps: number): string {
  if (!speedMps || speedMps <= 0) return "—";
  const paceSeconds = 1000 / speedMps;
  const mins = Math.floor(paceSeconds / 60);
  const secs = Math.round(paceSeconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")} /km`;
}
