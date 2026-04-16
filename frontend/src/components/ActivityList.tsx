import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import { fetchActivities, fetchSportTypes } from "../api/client";

export default function ActivityList() {
  const [sportType, setSportType] = useState<string>("");
  const [days, setDays] = useState(30);
  const navigate = useNavigate();

  const { data: types } = useApi(fetchSportTypes);
  const { data: activities, loading, error } = useApi(
    () => fetchActivities({ sport_type: sportType || undefined, days, limit: 100 }),
    [sportType, days]
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
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={365}>Last year</option>
        </select>
      </div>

      {loading && <div className="loading">Loading activities...</div>}
      {error && <div className="error">{error}</div>}

      {activities && activities.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Name</th>
                <th>Type</th>
                <th>Distance</th>
                <th>Duration</th>
                <th>Avg HR</th>
                <th>Calories</th>
              </tr>
            </thead>
            <tbody>
              {activities.map((a: any) => (
                <tr key={a.id} onClick={() => navigate(`/activities/${a.id}`)}>
                  <td>{formatDate(a.start_date_local || a.start_date)}</td>
                  <td>{a.name}</td>
                  <td>{a.sport_type}</td>
                  <td>{a.distance ? `${(a.distance / 1000).toFixed(1)} km` : "—"}</td>
                  <td>{formatDuration(a.moving_time)}</td>
                  <td>{a.average_hr ? `${Math.round(a.average_hr)}` : "—"}</td>
                  <td>{a.calories ? Math.round(a.calories) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {activities && activities.length === 0 && (
        <div className="card">No activities found for the selected filters.</div>
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function formatDuration(seconds?: number): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}
