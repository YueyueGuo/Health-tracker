import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import {
  fetchStrengthSessions,
  fetchStrengthSession,
  fetchStrengthProgression,
  fetchStrengthExercises,
  deleteStrengthSet,
  type StrengthSessionDetail,
} from "../api/strength";
import StrengthProgressionChart from "../components/StrengthProgressionChart";

/**
 * Strength dashboard.
 *
 * Left column: list of recent sessions (grouped by date). Clicking a
 *   session row loads its detail (per-exercise breakdown) inline.
 * Right column: progression chart for a selected exercise, with the
 *   exercise dropdown populated from /api/strength/exercises.
 */
export default function Strength() {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedExercise, setSelectedExercise] = useState<string>("");
  const [progressionDays, setProgressionDays] = useState(180);
  const [refreshKey, setRefreshKey] = useState(0);

  const { data: sessions, loading: sessionsLoading, error: sessionsError } = useApi(
    () => fetchStrengthSessions(30),
    [refreshKey]
  );
  const { data: exercises } = useApi(() => fetchStrengthExercises(), [refreshKey]);

  // Default-select the newest session the first time sessions load.
  useEffect(() => {
    if (!selectedDate && sessions && sessions.length > 0) {
      setSelectedDate(sessions[0].date);
    }
  }, [sessions, selectedDate]);

  // Default-select the first exercise once we have any.
  useEffect(() => {
    if (!selectedExercise && exercises && exercises.length > 0) {
      setSelectedExercise(exercises[0]);
    }
  }, [exercises, selectedExercise]);

  const { data: sessionDetail, loading: detailLoading } = useApi(
    () =>
      selectedDate
        ? fetchStrengthSession(selectedDate)
        : Promise.resolve<StrengthSessionDetail | null>(null),
    [selectedDate, refreshKey]
  );

  const { data: progression } = useApi(
    () =>
      selectedExercise
        ? fetchStrengthProgression(selectedExercise, progressionDays)
        : Promise.resolve([]),
    [selectedExercise, progressionDays, refreshKey]
  );

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this set?")) return;
    try {
      await deleteStrengthSet(id);
      setRefreshKey((k) => k + 1);
    } catch (e: any) {
      alert(e.message || "Delete failed");
    }
  };

  if (sessionsLoading) return <div className="loading">Loading strength sessions...</div>;
  if (sessionsError) return <div className="error">{sessionsError}</div>;

  return (
    <div>
      <div
        className="page-header"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}
      >
        <div>
          <h1>Strength</h1>
          <p>Manually-logged sets, reps, and weights</p>
        </div>
        <Link to="/strength/new" className="btn" style={{ textDecoration: "none" }}>
          + Add Session
        </Link>
      </div>

      {(!sessions || sessions.length === 0) && (
        <div className="card">
          No strength sessions yet. <Link to="/strength/new">Log your first session →</Link>
        </div>
      )}

      {sessions && sessions.length > 0 && (
        <div className="strength-grid">
          {/* ── Left: session list + selected session detail ── */}
          <div>
            <div className="card" style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "24px 24px 0 24px" }}>
                <h2>Recent Sessions</h2>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Exercises</th>
                    <th>Sets</th>
                    <th>Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr
                      key={s.date}
                      onClick={() => setSelectedDate(s.date)}
                      className={selectedDate === s.date ? "row-selected" : ""}
                    >
                      <td>{formatShortDate(s.date)}</td>
                      <td>{s.exercise_count}</td>
                      <td>{s.total_sets}</td>
                      <td>{formatVolume(s.total_volume_kg)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {detailLoading && <div className="loading">Loading session...</div>}
            {sessionDetail && (
              <SessionDetail session={sessionDetail} onDelete={handleDelete} />
            )}
          </div>

          {/* ── Right: progression chart ── */}
          <div>
            <div className="card">
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 16,
                  gap: 12,
                  flexWrap: "wrap",
                }}
              >
                <h2 style={{ margin: 0 }}>Progression</h2>
                <div style={{ display: "flex", gap: 8 }}>
                  <select
                    value={selectedExercise}
                    onChange={(e) => setSelectedExercise(e.target.value)}
                    disabled={!exercises || exercises.length === 0}
                  >
                    {(!exercises || exercises.length === 0) && <option>No exercises</option>}
                    {exercises?.map((ex) => (
                      <option key={ex} value={ex}>
                        {ex}
                      </option>
                    ))}
                  </select>
                  <select
                    value={progressionDays}
                    onChange={(e) => setProgressionDays(Number(e.target.value))}
                  >
                    <option value={30}>30d</option>
                    <option value={90}>90d</option>
                    <option value={180}>180d</option>
                    <option value={365}>1y</option>
                  </select>
                </div>
              </div>
              {selectedExercise ? (
                <StrengthProgressionChart
                  data={progression || []}
                  exerciseName={selectedExercise}
                />
              ) : (
                <div style={{ color: "var(--text-muted)", padding: 24 }}>
                  Add a session to see progression.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SessionDetail({
  session,
  onDelete,
}: {
  session: StrengthSessionDetail;
  onDelete: (id: number) => void | Promise<void>;
}) {
  return (
    <div className="card">
      <h2>{formatLongDate(session.date)}</h2>
      {session.exercises.map((ex) => (
        <div key={ex.name} className="exercise-block">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              marginBottom: 8,
            }}
          >
            <strong>{ex.name}</strong>
            <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
              {ex.max_weight != null ? `Top: ${ex.max_weight} kg · ` : ""}
              Vol: {formatVolume(ex.total_volume)}
              {ex.est_1rm != null ? ` · Est. 1RM: ${ex.est_1rm.toFixed(1)} kg` : ""}
            </span>
          </div>
          <table className="data-table data-table-compact">
            <thead>
              <tr>
                <th>Set</th>
                <th>Reps</th>
                <th>Weight</th>
                <th>RPE</th>
                <th>Notes</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {ex.sets.map((s) => (
                <tr key={s.id} style={{ cursor: "default" }}>
                  <td>{s.set_number}</td>
                  <td>{s.reps}</td>
                  <td>{s.weight_kg != null ? `${s.weight_kg} kg` : "—"}</td>
                  <td>{s.rpe ?? "—"}</td>
                  <td
                    style={{
                      color: "var(--text-muted)",
                      fontSize: 12,
                      maxWidth: 240,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {s.notes ?? ""}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => onDelete(s.id)}
                      aria-label="Delete set"
                    >
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function formatShortDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function formatLongDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatVolume(kg: number | null | undefined): string {
  if (kg == null || kg === 0) return "—";
  if (kg >= 1000) return `${(kg / 1000).toFixed(1)}t`;
  return `${Math.round(kg)} kg`;
}
