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
import {
  fetchActivity,
  fetchActivityStreams,
  fetchWorkoutAnalysis,
  reclassifyActivity,
  type ZoneDistribution,
} from "../api/client";
import { getActivityWeather } from "../api/weather";
import { useEffect, useRef, useState } from "react";
import ClassificationBadge from "./ClassificationBadge";
import LocationPicker from "./LocationPicker";
import WeatherCard from "./WeatherCard";
import {
  formatDistance,
  formatElevation,
  formatPaceOrSpeed,
  isCyclingSport,
  useUnits,
  type UnitSystem,
} from "../hooks/useUnits";

// Mirrors the tier thresholds in backend/services/classifier.py. Kept in
// sync manually — if you change one, change the other.
const ALT_LOW_M = 610;
const ALT_MODERATE_M = 1500;
const ALT_HIGH_M = 2500;

function altitudeTierLabel(elevation_m: number): string | null {
  if (elevation_m >= ALT_HIGH_M) return "high altitude";
  if (elevation_m >= ALT_MODERATE_M) return "moderate altitude";
  if (elevation_m >= ALT_LOW_M) return "low altitude";
  return null;
}

export default function ActivityDetail() {
  const { id } = useParams<{ id: string }>();
  const activityId = Number(id);
  const { units } = useUnits();
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
  // Tracks the most recently-requested activity id. Used both to dedupe
  // under React StrictMode's double-mount (second mount sees the ref already
  // set and short-circuits) AND to detect stale fetches when the user
  // navigates between activities mid-request.
  const latestStreamId = useRef<number | null>(null);

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

  // Auto-load stream data as soon as the activity detail page mounts. The
  // backend caches the stream JSON in activity_streams on first hit, so
  // subsequent views of the same activity are free; only the first view
  // spends a Strava read.
  //
  // We use a ref (`latestStreamId`) rather than a cleanup-based cancelled
  // flag because React StrictMode's synthetic cleanup-then-remount would
  // otherwise race with our own fetch: the first mount's cleanup flips
  // cancelled=true, the second mount's dedupe skips the fetch, and the
  // first fetch's completion then silently drops its result because
  // cancelled is true → state stays empty. Tracking "the id we most
  // recently kicked off a fetch for" on the ref lets the fetch resolver
  // check if it's still the active request (ref === myId) without depending
  // on closure-scoped cleanup state.
  useEffect(() => {
    if (!Number.isFinite(activityId)) return;
    if (latestStreamId.current === activityId) return;
    const myId = activityId;
    latestStreamId.current = myId;
    setStreams(null);
    setStreamsError(null);
    setStreamsLoading(true);
    (async () => {
      try {
        const s = await fetchActivityStreams(myId);
        if (latestStreamId.current !== myId) return; // user navigated away
        setStreams(s);
      } catch (e: any) {
        if (latestStreamId.current !== myId) return;
        setStreamsError(e?.message || "Failed to load streams");
      } finally {
        if (latestStreamId.current === myId) setStreamsLoading(false);
      }
    })();
  }, [activityId]);

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
            <div className="value">{formatDistance(activity.distance, units)}</div>
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
            <div className="label">
              {isCyclingSport(activity.sport_type) ? "Avg Speed" : "Avg Pace"}
            </div>
            <div className="value">
              {formatPaceOrSpeed(activity.average_speed, activity.sport_type, units)}
            </div>
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
            <div className="label">Elevation Gain</div>
            <div className="value">{formatElevation(activity.total_elevation, units)}</div>
          </div>
        )}
        {activity.base_elevation_m != null &&
          activity.base_elevation_m >= ALT_LOW_M && (
            <div className="metric-card">
              <div className="label">Base Altitude</div>
              <div className="value">
                {formatElevation(activity.base_elevation_m, units)}
              </div>
              {(() => {
                const tier = altitudeTierLabel(activity.base_elevation_m!);
                return tier ? (
                  <div className="subtext">{tier}</div>
                ) : null;
              })()}
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

      {/* Indoor / no-GPS activities: let the user attach a saved location
          so we can still compute base altitude. */}
      {activity.start_lat == null && activity.start_lng == null && (
        <LocationPicker
          activityId={activityId}
          currentLocationId={activity.location_id}
          onChange={reload}
        />
      )}

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
                  <td>{formatDistance(lap.distance, units)}</td>
                  <td>{formatDuration(lap.moving_time)}</td>
                  <td>
                    {lap.average_speed
                      ? formatPaceOrSpeed(lap.average_speed, activity.sport_type, units)
                      : "—"}
                  </td>
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
        {streamsLoading && <div className="loading">Loading streams...</div>}
        {streamsError && !streams && (
          <div className="error">{streamsError}</div>
        )}
        {streams && (
          <StreamsChart
            streams={streams}
            units={units}
            sportType={activity.sport_type}
          />
        )}
        {!streams && !streamsLoading && !streamsError && (
          <div style={{ color: "var(--text-muted)" }}>
            No stream data available for this activity.
          </div>
        )}
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

// Named HR zones — standard endurance coaching vocabulary (Recovery/Endurance/
// Tempo/Threshold/VO2max/Anaerobic/Neuromuscular). Indexed by bucket position;
// truncated to the actual bucket count (Strava returns 5 by default, 7 if the
// user has split zones).
const HR_ZONE_NAMES = [
  "Recovery",
  "Endurance",
  "Tempo",
  "Threshold",
  "VO2max",
  "Anaerobic",
  "Neuromuscular",
];

function zoneTitle(type: string): string {
  if (type === "heartrate") return "Heart Rate";
  if (type === "power") return "Power";
  if (type === "pace") return "Pace";
  return type;
}

function ZoneChart({ zone }: { zone: ZoneDistribution }) {
  const buckets = zone.distribution_buckets;
  const totalTime = buckets.reduce((acc, b) => acc + (b.time || 0), 0);
  if (!buckets.length || totalTime <= 0) return null;

  return (
    <div className="zone-chart">
      <div className="zone-chart__title">{zoneTitle(zone.type)}</div>
      {buckets.map((b, i) => {
        const time = b.time || 0;
        const pct = Math.round((100 * time) / totalTime);
        const minutes = Math.round(time / 60);
        const colorVar = `var(--zone-${Math.min(i + 1, 7)})`;
        const name =
          zone.type === "heartrate" && i < HR_ZONE_NAMES.length
            ? HR_ZONE_NAMES[i]
            : null;
        const range = zoneBucketRange(zone.type, b);
        return (
          <div className="zone-row" key={i}>
            <div className="zone-row__label">
              <span>Z{i + 1}</span>
              {name && <span className="zone-name">{name}</span>}
              <span className="zone-name"> · {range}</span>
            </div>
            <div className="zone-row__track">
              <div
                className="zone-row__fill"
                style={{ width: `${pct}%`, background: colorVar }}
              />
            </div>
            <div className="zone-row__value">
              {pct}% · {minutes} min
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StreamsChart({
  streams,
  units,
  sportType,
}: {
  streams: Record<string, number[]>;
  units: UnitSystem;
  sportType: string | null | undefined;
}) {
  const hasHR = (streams.heartrate?.length ?? 0) > 0;
  const hasPace = (streams.velocity_smooth?.length ?? 0) > 0;
  const hasAltitude = (streams.altitude?.length ?? 0) > 0;
  const timeData = streams.time || [];
  const cycling = isCyclingSport(sportType);

  // For cycling: render speed (mph or km/h). For running/other: render pace
  // in decimal minutes per mile/km so the y-axis reads natively.
  const metersPerUnit = units === "imperial" ? 1609.344 : 1000;
  const chartData = timeData.map((t, i) => {
    const mps = streams.velocity_smooth?.[i];
    let yValue: number | undefined;
    if (mps && mps > 0) {
      if (cycling) {
        // Speed → mph or km/h
        yValue = units === "imperial"
          ? (mps * 3600) / 1609.344
          : (mps * 3600) / 1000;
      } else {
        // Pace → min per mile / km
        yValue = metersPerUnit / mps / 60;
      }
    }
    return {
      time: Math.round(t / 60),
      hr: streams.heartrate?.[i],
      speed: yValue,
      altitude: streams.altitude?.[i],
    };
  });

  if (chartData.length === 0 || (!hasHR && !hasPace && !hasAltitude)) {
    return <div style={{ color: "var(--text-muted)" }}>No stream data available.</div>;
  }

  const paceLabel = cycling
    ? units === "imperial"
      ? "Speed (mph)"
      : "Speed (km/h)"
    : units === "imperial"
      ? "Pace (min/mi)"
      : "Pace (min/km)";

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
          <YAxis
            yAxisId="pace"
            orientation="right"
            stroke="#6366f1"
            reversed={!cycling}
            domain={["auto", "auto"]}
          />
        )}
        <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }} />
        <Legend />
        {hasHR && (
          <Line yAxisId="hr" type="monotone" dataKey="hr" stroke="#ef4444" dot={false} name="Heart Rate (bpm)" />
        )}
        {hasPace && (
          <Line yAxisId="pace" type="monotone" dataKey="speed" stroke="#6366f1" dot={false} name={paceLabel} />
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

// Range-only label used by the labeled-bar ZoneChart — returns just the
// numeric range + unit (e.g. "120–140 bpm", "≥180 bpm", "120–180 W") because
// the `Z{i+1}` and zone name are rendered as separate spans with their own
// styling.
function zoneBucketRange(type: string, b: { min: number; max: number }): string {
  const suffix = b.max === -1 ? `\u2265${b.min}` : `${b.min}–${b.max}`;
  if (type === "heartrate") return `${suffix} bpm`;
  if (type === "power") return `${suffix} W`;
  return suffix;
}
