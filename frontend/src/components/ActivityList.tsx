import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import {
  fetchActivities,
  fetchSportTypes,
  type ActivitySummary,
  type ClassificationType,
} from "../api/client";
import {
  formatDistance,
  formatPaceOrSpeed,
  isCyclingSport,
  useUnits,
} from "../hooks/useUnits";
import ClassificationBadge from "./ClassificationBadge";

const CLASSIFICATION_OPTIONS: Exclude<ClassificationType, null>[] = [
  "easy",
  "tempo",
  "intervals",
  "race",
  "recovery",
  "endurance",
  "mixed",
];

export default function ActivityList() {
  const [sportType, setSportType] = useState<string>("");
  const [classification, setClassification] = useState<string>("");
  const [days, setDays] = useState(30);
  const navigate = useNavigate();
  const { units } = useUnits();

  const { data: types } = useApi(fetchSportTypes);
  const { data: activities, loading, error } = useApi(
    () => fetchActivities({ sport_type: sportType || undefined, days, limit: 200 }),
    [sportType, days]
  );

  // Classification filter is client-side (the API doesn't filter on it yet).
  const filtered = activities?.filter(
    (a) => !classification || a.classification_type === classification
  );

  return (
    <div>
      <div className="page-header">
        <h1>Activities</h1>
        <p>Your workout history</p>
      </div>

      <div className="filter-bar">
        <select value={sportType} onChange={(e) => setSportType(e.target.value)}>
          <option value="">All Sports</option>
          {types?.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select value={classification} onChange={(e) => setClassification(e.target.value)}>
          <option value="">All Classifications</option>
          {CLASSIFICATION_OPTIONS.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={365}>Last year</option>
        </select>
        {filtered && activities && (
          <span style={{ color: "var(--text-muted)", fontSize: 13 }}>
            {filtered.length}
            {filtered.length !== activities.length ? ` / ${activities.length}` : ""} result
            {filtered.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {loading && <div className="loading">Loading activities...</div>}
      {error && <div className="error">{error}</div>}

      {filtered && filtered.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Name</th>
                <th>Type</th>
                <th>Classification</th>
                <th>Distance</th>
                <th>Duration</th>
                <th>Pace / Avg HR</th>
                <th>Relative Effort</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a) => (
                <tr key={a.id} onClick={() => navigate(`/activities/${a.id}`)}>
                  <td>{formatDate(a.start_date_local || a.start_date)}</td>
                  <td>{a.name}</td>
                  <td>{a.sport_type}</td>
                  <td>
                    <ClassificationBadge
                      type={a.classification_type}
                      flags={a.classification_flags}
                      compact
                    />
                  </td>
                  <td>{formatDistance(a.distance, units)}</td>
                  <td>{formatDuration(a.moving_time)}</td>
                  <td>{formatPaceOrHr(a, units)}</td>
                  <td>{a.suffer_score ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {filtered && filtered.length === 0 && (
        <div className="card">No activities found for the selected filters.</div>
      )}
    </div>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function formatDuration(seconds: number | null): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatPaceOrHr(
  a: ActivitySummary,
  units: "imperial" | "metric"
): string {
  const sport = (a.sport_type || "").toLowerCase();
  // Runs → pace; rides → speed; everything else → average HR if present.
  if ((sport.includes("run") || sport.includes("walk") || isCyclingSport(a.sport_type)) && a.average_speed) {
    return formatPaceOrSpeed(a.average_speed, a.sport_type, units);
  }
  if (a.average_hr) {
    return `${Math.round(a.average_hr)} bpm`;
  }
  return "—";
}
