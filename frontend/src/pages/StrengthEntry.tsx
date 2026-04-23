import { useState, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import {
  createStrengthSession,
  fetchStrengthExercises,
  type StrengthSetInput,
} from "../api/strength";
import { fetchActivities, type ActivitySummary } from "../api/activities";

/**
 * Form for adding a strength session.
 *
 * * Date picker (defaults to today).
 * * Optional link to a recent Strava WeightTraining activity.
 * * Dynamic rows: exercise (with autocomplete), set #, reps, weight,
 *   RPE, notes. Add / remove rows. "Save" POSTs the batch to
 *   /api/strength/sets.
 */

type RowState = {
  key: number;
  exercise_name: string;
  set_number: number;
  reps: number | "";
  weight_kg: number | "";
  rpe: number | "";
  notes: string;
};

const emptyRow = (key: number, exercise_name = "", set_number = 1): RowState => ({
  key,
  exercise_name,
  set_number,
  reps: "",
  weight_kg: "",
  rpe: "",
  notes: "",
});

export default function StrengthEntry() {
  const navigate = useNavigate();
  const today = new Date().toISOString().slice(0, 10);

  const [date, setDate] = useState(today);
  const [activityId, setActivityId] = useState<number | null>(null);
  const [rows, setRows] = useState<RowState[]>([emptyRow(Date.now())]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Autocomplete source. We fetch all distinct names once and filter
  // client-side per row — keeps the UX snappy without per-keystroke API hits.
  const { data: exercises } = useApi(() => fetchStrengthExercises(), []);

  // Recent Strava WeightTraining activities for the "link" dropdown.
  const { data: activities } = useApi(
    () => fetchActivities({ sport_type: "WeightTraining", days: 30, limit: 20 }),
    []
  );

  const addRow = () => {
    // If the last row has an exercise, auto-increment the set number
    // for that exercise to reduce typing.
    const last = rows[rows.length - 1];
    let nextSetNumber = 1;
    let exerciseName = "";
    if (last && last.exercise_name) {
      const sameExerciseRows = rows.filter(
        (r) => r.exercise_name.trim().toLowerCase() === last.exercise_name.trim().toLowerCase()
      );
      nextSetNumber = sameExerciseRows.length + 1;
      exerciseName = last.exercise_name;
    }
    setRows((rs) => [...rs, emptyRow(Date.now() + rs.length, exerciseName, nextSetNumber)]);
  };

  const removeRow = (key: number) => {
    setRows((rs) => (rs.length > 1 ? rs.filter((r) => r.key !== key) : rs));
  };

  const updateRow = (key: number, patch: Partial<RowState>) => {
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  };

  const canSave = useMemo(
    () => rows.every((r) => r.exercise_name.trim().length > 0 && r.reps !== "" && Number(r.reps) >= 1),
    [rows]
  );

  const handleSave = async () => {
    setError(null);
    setSaving(true);
    try {
      const payload: StrengthSetInput[] = rows.map((r) => ({
        exercise_name: r.exercise_name.trim(),
        set_number: Number(r.set_number),
        reps: Number(r.reps),
        weight_kg: r.weight_kg === "" ? null : Number(r.weight_kg),
        rpe: r.rpe === "" ? null : Number(r.rpe),
        notes: r.notes.trim() === "" ? null : r.notes.trim(),
      }));
      await createStrengthSession({ date, activity_id: activityId, sets: payload });
      navigate("/strength");
    } catch (e: any) {
      setError(e.message || "Failed to save session");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Log Strength Session</h1>
        <p>
          Enter each set on its own row. <Link to="/strength">← Back to sessions</Link>
        </p>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <div className="filter-bar" style={{ flexWrap: "wrap" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}>
            <span style={{ color: "var(--text-muted)", textTransform: "uppercase" }}>Date</span>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="input"
            />
          </label>
          <label
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 4,
              fontSize: 12,
              minWidth: 260,
            }}
          >
            <span style={{ color: "var(--text-muted)", textTransform: "uppercase" }}>
              Link Strava activity (optional)
            </span>
            <select
              value={activityId ?? ""}
              onChange={(e) =>
                setActivityId(e.target.value === "" ? null : Number(e.target.value))
              }
            >
              <option value="">(none)</option>
              {activities?.map((a) => (
                <option key={a.id} value={a.id}>
                  {activityLabel(a)}
                </option>
              ))}
            </select>
          </label>
        </div>

        <table className="data-table data-table-compact" style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th style={{ minWidth: 180 }}>Exercise</th>
              <th style={{ width: 60 }}>Set</th>
              <th style={{ width: 80 }}>Reps</th>
              <th style={{ width: 100 }}>Weight (kg)</th>
              <th style={{ width: 70 }}>RPE</th>
              <th>Notes</th>
              <th style={{ width: 40 }}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} style={{ cursor: "default" }}>
                <td>
                  <input
                    className="input"
                    list="exercise-list"
                    placeholder="Exercise"
                    value={row.exercise_name}
                    onChange={(e) => updateRow(row.key, { exercise_name: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    value={row.set_number}
                    onChange={(e) =>
                      updateRow(row.key, { set_number: Number(e.target.value) || 1 })
                    }
                  />
                </td>
                <td>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    value={row.reps}
                    onChange={(e) =>
                      updateRow(row.key, {
                        reps: e.target.value === "" ? "" : Number(e.target.value),
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step="0.5"
                    value={row.weight_kg}
                    onChange={(e) =>
                      updateRow(row.key, {
                        weight_kg: e.target.value === "" ? "" : Number(e.target.value),
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={10}
                    step="0.5"
                    value={row.rpe}
                    onChange={(e) =>
                      updateRow(row.key, {
                        rpe: e.target.value === "" ? "" : Number(e.target.value),
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    className="input"
                    type="text"
                    value={row.notes}
                    onChange={(e) => updateRow(row.key, { notes: e.target.value })}
                  />
                </td>
                <td style={{ textAlign: "right" }}>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => removeRow(row.key)}
                    disabled={rows.length <= 1}
                    aria-label="Remove row"
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <datalist id="exercise-list">
          {exercises?.map((ex) => (
            <option key={ex} value={ex} />
          ))}
        </datalist>

        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <button type="button" className="btn btn-secondary" onClick={addRow}>
            + Add set
          </button>
          <button
            type="button"
            className="btn"
            onClick={handleSave}
            disabled={!canSave || saving}
          >
            {saving ? "Saving..." : "Save session"}
          </button>
          <Link to="/strength" className="btn btn-secondary" style={{ textDecoration: "none" }}>
            Cancel
          </Link>
        </div>
      </div>
    </div>
  );
}

function activityLabel(a: ActivitySummary): string {
  const d = a.start_date_local || a.start_date;
  const datePart = d
    ? new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : "";
  const mins = a.moving_time ? Math.round(a.moving_time / 60) : null;
  return `${datePart} · ${a.name}${mins != null ? ` (${mins}m)` : ""}`;
}
