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
  BarChart,
  Bar,
} from "recharts";
import { useApi } from "../hooks/useApi";
import {
  fetchActivity,
  fetchActivityStreams,
  fetchWorkoutAnalysis,
  reclassifyActivity,
  type ActivityLap,
  type ZoneDistribution,
} from "../api/client";
import { getActivityWeather } from "../api/weather";
import { useState } from "react";
import ClassificationBadge from "./ClassificationBadge";
import WeatherCard from "./WeatherCard";

export default function ActivityDetail() {
  const { id } = useParams<{ id: string }>();
  const activityId = Number(id);
  const { data: activity, loading, error, reload } = useApi(
    () => fetchActivity(activityId),
    [activityId]
  );
  // Weather is fetched independently so a missing snapshot (404) doesn't
  // block the rest of the detail view. We always request ``?raw=true``
  // so the card can render the OpenWeatherMap icon when available.
  const { data: weather } = useApi(
    () => getActivityWeather(activityId, { raw: true }),
    [activityId]
  );
  const [analysis, setAnalysis] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [streams, setStreams] = useState<Record<string, number[]> | null>(null);
  const [streamsLoading, setStreamsLoading] = useState(false);
  const [streamsError, setStreamsError] = useState<string | null>(null);
  const [reclassifying, setReclassifying] = useState(false);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    try {
      const result = await fetchWorkoutAnalysis(activityId);
      setAnalysis(result.answer);
    } catch (e: any) {
      setAnalysis(`Error: ${e.message}`);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleLoadStreams = async () => {
    setStreamsLoading(true);
    setStreamsError(null);
    try {
      const s = await fetchActivityStreams(activityId);
      setStreams(s);
    } catch (e: any) {
      setStreamsError(e.message || "Failed to load streams");
    } finally {
      setStreamsLoading(false);
    }
  };

  const handleReclassify = async () => {
    setReclassifying(true);
    try {
      await reclassifyActivity(activityId);
      await reload();
    } finally {
      setReclassifying(false);
    }
  };

  if (loading) return <div className="loading">Loading activity...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!activity) return null;

  return (
    <div>
      <div className="page-header">
        <h1>{activity.name}</h1>
        <p>
          {activity.sport_type} &middot;{" "}
          {activity.start_date_local &&
            new Date(activity.start_date_local).toLocaleDateString("en-US", {
              weekday: "long",
              month: "long",
              day: "numeric",
              year: "numeric",
            })}
        </p>
        <div style={{ marginTop: 8 }}>
          <ClassificationBadge
            type={activity.classification_type}
            flags={activity.classification_flags}
          />
          {activity.enrichment_status !== "complete" && (
            <span className="chip" style={{ marginLeft: 8 }}>
              {activity.enrichment_status}
            </span>
          )}
          {activity.classification_type && (
            <button
              onClick={handleReclassify}
              disabled={reclassifying}
              style={{
                marginLeft: 12,
                background: "transparent",
                border: "1px solid var(--border)",
                color: "var(--text-muted)",
                fontSize: 11,
                padding: "2px 10px",
                borderRadius: 4,
                cursor: "pointer",
              }}
            >
              {reclassifying ? "Reclassifying…" : "Reclassify"}
            </button>
          )}
        </div>
      </div>

      <div className="metric-grid">
        {activity.distance != null && (
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
        {activity.average_power != null && (
          <div className="metric-card">
            <div className="label">Avg Power</div>
            <div className="value">{Math.round(activity.average_power)} W</div>
            {activity.weighted_avg_power != null && (
              <div className="subtext">
                Normalized: {Math.round(activity.weighted_avg_power)} W
                {activity.device_watts === false && " • estimated"}
                {activity.device_watts === true && " • power meter"}
              </div>
            )}
          </div>
        )}
        {activity.total_elevation != null && activity.total_elevation > 0 && (
          <div className="metric-card">
            <div className="label">Elevation</div>
            <div className="value">{Math.round(activity.total_elevation)} m</div>
          </div>
        )}
        {activity.kilojoules != null && (
          <div className="metric-card">
            <div className="label">Work</div>
            <div className="value">{Math.round(activity.kilojoules)} kJ</div>
            {activity.calories != null && (
              <div className="subtext">{Math.round(activity.calories)} kcal</div>
            )}
          </div>
        )}
        {activity.suffer_score != null && (
          <div className="metric-card">
            <div className="label">Relative Effort</div>
            <div className="value">{activity.suffer_score}</div>
          </div>
        )}
      </div>

      <WeatherCard weather={weather} />

      {activity.laps && activity.laps.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <h2 style={{ padding: "20px 24px 12px" }}>Laps</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Distance</th>
                <th>Moving</th>
                <th>Pace</th>
                <th>Avg HR</th>
                <th>Avg Power</th>
                <th>Zone</th>
              </tr>
            </thead>
            <tbody>
              {activity.laps.map((lap) => (
                <tr key={lap.lap_index} className={laneClass(lap.pace_zone)}>
                  <td>{lap.lap_index}</td>
                  <td>{lap.distance ? formatDistanceM(lap.distance) : "—"}</td>
                  <td>{formatDuration(lap.moving_time)}</td>
                  <td>{lap.average_speed ? formatPace(lap.average_speed) : "—"}</td>
                  <td>{lap.average_heartrate ? Math.round(lap.average_heartrate) : "—"}</td>
                  <td>{lap.average_watts ? `${Math.round(lap.average_watts)} W` : "—"}</td>
                  <td>{lap.pace_zone ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {activity.zones && activity.zones.length > 0 && (
        <div className="card">
          <h2>Time in Zone</h2>
          {activity.zones.map((z) => (
            <ZoneChart key={z.type} zone={z} />
          ))}
        </div>
      )}

      <div className="card">
        <h2>Stream Data</h2>
        {!streams && !streamsLoading && (
          <div>
            <p style={{ color: "var(--text-muted)", marginBottom: 12 }}>
              Per-sample heart rate, pace, and elevation. Fetched on demand from Strava.
              {activity.streams_cached && " (Previously cached.)"}
            </p>
            <button className="btn" onClick={handleLoadStreams}>
              Load Streams
            </button>
          </div>
        )}
        {streamsLoading && <div className="loading">Loading streams...</div>}
        {streamsError && <div className="error">{streamsError}</div>}
        {streams && <StreamsChart streams={streams} />}
      </div>

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

// ── Sub-components ─────────────────────────────────────────────────────

function ZoneChart({ zone }: { zone: ZoneDistribution }) {
  const data = zone.distribution_buckets.map((b, i) => ({
    name: zoneBucketLabel(zone.type, b, i),
    minutes: Math.round((b.time || 0) / 60),
    time: b.time,
  }));
  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ color: "var(--text-muted)", fontSize: 12, marginBottom: 8, textTransform: "uppercase" }}>
        {zone.type}
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={data} layout="vertical" margin={{ left: 40, right: 20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis type="number" stroke="var(--text-muted)" />
          <YAxis type="category" dataKey="name" stroke="var(--text-muted)" width={90} />
          <Tooltip
            contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            formatter={(value) => [`${value as number} min`, "Time"]}
          />
          <Bar dataKey="minutes" fill="#6366f1" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function StreamsChart({ streams }: { streams: Record<string, number[]> }) {
  const hasHR = (streams.heartrate?.length ?? 0) > 0;
  const hasPace = (streams.velocity_smooth?.length ?? 0) > 0;
  const hasAltitude = (streams.altitude?.length ?? 0) > 0;
  const timeData = streams.time || [];

  const chartData = timeData.map((t, i) => ({
    time: Math.round(t / 60),
    hr: streams.heartrate?.[i],
    speed: streams.velocity_smooth?.[i]
      ? 1000 / streams.velocity_smooth[i]! / 60
      : undefined,
    altitude: streams.altitude?.[i],
  }));

  if (chartData.length === 0 || (!hasHR && !hasPace && !hasAltitude)) {
    return <div style={{ color: "var(--text-muted)" }}>No stream data available.</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={350}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis
          dataKey="time"
          label={{ value: "Minutes", position: "insideBottom", offset: -5, fill: "var(--text-muted)" }}
          stroke="var(--text-muted)"
        />
        {hasHR && <YAxis yAxisId="hr" orientation="left" stroke="#ef4444" domain={["auto", "auto"]} />}
        {hasPace && (
          <YAxis yAxisId="pace" orientation="right" stroke="#6366f1" reversed domain={["auto", "auto"]} />
        )}
        <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }} />
        <Legend />
        {hasHR && (
          <Line yAxisId="hr" type="monotone" dataKey="hr" stroke="#ef4444" dot={false} name="Heart Rate (bpm)" />
        )}
        {hasPace && (
          <Line yAxisId="pace" type="monotone" dataKey="speed" stroke="#6366f1" dot={false} name="Pace (min/km)" />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function laneClass(paceZone: number | null | undefined): string {
  if (paceZone == null) return "";
  return `lap-row-z${Math.max(1, Math.min(6, paceZone))}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`;
}

function formatPace(speedMps: number | null | undefined): string {
  if (!speedMps || speedMps <= 0) return "—";
  const paceSeconds = 1000 / speedMps;
  const mins = Math.floor(paceSeconds / 60);
  const secs = Math.round(paceSeconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")} /km`;
}

function formatDistanceM(m: number): string {
  if (m >= 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${Math.round(m)} m`;
}

function zoneBucketLabel(type: string, b: { min: number; max: number }, i: number): string {
  const suffix = b.max === -1 ? `\u2265${b.min}` : `${b.min}–${b.max}`;
  if (type === "heartrate") return `Z${i + 1} (${suffix} bpm)`;
  if (type === "power") return `${suffix} W`;
  return `Z${i + 1}`;
}
