import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import {
  createStrengthSession,
  fetchStrengthExercises,
  type StrengthSetInput,
} from "../api/strength";
import { fetchActivities, type ActivitySummary } from "../api/client";

/**
 * Form for adding a strength session. Two modes:
 *
 *   * **Live** (default) — tap "Log set" between reps. Each tap stamps
 *     the row with `performed_at = new Date()`. A rest timer shows
 *     time-since-last-log to help pace supersets. When the linked
 *     Strava activity's HR stream is cached, the session detail view
 *     pairs each set with avg/max HR sliced from the 45s window ending
 *     at its timestamp.
 *   * **Retro** — classic batch form. No timestamps; the session still
 *     saves and renders, just without per-set HR pills.
 */

type RowState = {
  key: number;
  exercise_name: string;
  set_number: number;
  reps: number | "";
  weight_kg: number | "";
  rpe: number | "";
  notes: string;
  /** ISO string (naive local) captured when user taps "Log set".
   * Null until tapped. Ignored in retro mode. */
  performed_at: string | null;
};

type EntryMode = "live" | "retro";

const emptyRow = (key: number, exercise_name = "", set_number = 1): RowState => ({
  key,
  exercise_name,
  set_number,
  reps: "",
  weight_kg: "",
  rpe: "",
  notes: "",
  performed_at: null,
});

/** Format `new Date()` → "YYYY-MM-DDTHH:mm:ss" (naive local, no tz).
 *  Matches the convention used everywhere else in the codebase. */
function toNaiveLocalIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

function formatClockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatRestTimer(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function StrengthEntry() {
  const navigate = useNavigate();
  const today = new Date().toISOString().slice(0, 10);

  const [mode, setMode] = useState<EntryMode>("live");
  const [date, setDate] = useState(today);
  const [activityId, setActivityId] = useState<number | null>(null);
  const [rows, setRows] = useState<RowState[]>([emptyRow(Date.now())]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // Autocomplete source. We fetch all distinct names once and filter
  // client-side per row — keeps the UX snappy without per-keystroke API hits.
  const { data: exercises } = useApi(() => fetchStrengthExercises(), []);

  // Recent Strava WeightTraining activities for the "link" dropdown.
  const { data: activities } = useApi(
    () => fetchActivities({ sport_type: "WeightTraining", days: 30, limit: 20 }),
    []
  );

  // Tick the rest timer once per second while in live mode.
  useEffect(() => {
    if (mode !== "live") return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [mode]);

  // Most recent `performed_at` across all rows — anchors the rest timer.
  const lastLoggedAt = useMemo(() => {
    const stamps = rows
      .map((r) => r.performed_at)
      .filter((s): s is string => !!s)
      .map((s) => new Date(s).getTime());
    return stamps.length ? Math.max(...stamps) : null;
  }, [rows]);

  const restSeconds =
    lastLoggedAt != null ? Math.max(0, Math.floor((now - lastLoggedAt) / 1000)) : null;

  // Focus the reps input on a newly-appended row (live mode only).
  const repsRefs = useRef<Map<number, HTMLInputElement | null>>(new Map());
  const pendingFocusKey = useRef<number | null>(null);
  useEffect(() => {
    if (pendingFocusKey.current == null) return;
    const el = repsRefs.current.get(pendingFocusKey.current);
    el?.focus();
    pendingFocusKey.current = null;
  }, [rows]);

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
    const newKey = Date.now() + rows.length;
    pendingFocusKey.current = newKey;
    setRows((rs) => [...rs, emptyRow(newKey, exerciseName, nextSetNumber)]);
  };

  const removeRow = (key: number) => {
    setRows((rs) => (rs.length > 1 ? rs.filter((r) => r.key !== key) : rs));
  };

  const updateRow = (key: number, patch: Partial<RowState>) => {
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  };

  /** Live mode: stamp the row with `now()` and auto-append the next row. */
  const logSet = (key: number) => {
    const row = rows.find((r) => r.key === key);
    if (!row) return;
    if (!row.exercise_name.trim() || row.reps === "" || Number(row.reps) < 1) {
      setError("Fill in exercise + reps before logging this set.");
      return;
    }
    setError(null);
    updateRow(key, { performed_at: toNaiveLocalIso(new Date()) });
    // Only auto-append if this row was the last one — otherwise respect
    // what the user was typing further down.
    if (rows[rows.length - 1].key === key) {
      addRow();
    }
  };

  const canSave = useMemo(() => {
    // Retro mode: every row must have exercise + reps.
    // Live mode: at least one logged row (unlogged drafts are ignored).
    if (mode === "retro") {
      return rows.every(
        (r) => r.exercise_name.trim().length > 0 && r.reps !== "" && Number(r.reps) >= 1
      );
    }
    return rows.some((r) => r.performed_at != null);
  }, [rows, mode]);

  const handleSave = async () => {
    setError(null);
    setSaving(true);
    try {
      const sourceRows =
        mode === "live"
          ? rows.filter((r) => r.performed_at != null)
          : rows;
      const payload: StrengthSetInput[] = sourceRows.map((r) => ({
        exercise_name: r.exercise_name.trim(),
        set_number: Number(r.set_number),
        reps: Number(r.reps),
        weight_kg: r.weight_kg === "" ? null : Number(r.weight_kg),
        rpe: r.rpe === "" ? null : Number(r.rpe),
        notes: r.notes.trim() === "" ? null : r.notes.trim(),
        performed_at: mode === "live" ? r.performed_at : null,
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
        <div className="filter-bar" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12 }}>
            <span style={{ color: "var(--text-muted)", textTransform: "uppercase" }}>Mode</span>
            <ModeToggle mode={mode} setMode={setMode} />
          </label>
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
          {mode === "live" && (
            <div style={{ marginLeft: "auto" }}>
              <RestTimerChip seconds={restSeconds} />
            </div>
          )}
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
              <th style={{ width: mode === "live" ? 120 : 40, textAlign: "right" }}></th>
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
                    ref={(el) => {
                      if (el) repsRefs.current.set(row.key, el);
                      else repsRefs.current.delete(row.key);
                    }}
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
                  {mode === "live" ? (
                    row.performed_at ? (
                      <span
                        style={{ color: "var(--accent)", fontSize: 12, whiteSpace: "nowrap" }}
                        title={row.performed_at}
                      >
                        ✓ {formatClockTime(row.performed_at)}
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn"
                        style={{ padding: "4px 10px", fontSize: 12 }}
                        onClick={() => logSet(row.key)}
                      >
                        Log set
                      </button>
                    )
                  ) : (
                    <button
                      type="button"
                      className="link-btn"
                      onClick={() => removeRow(row.key)}
                      disabled={rows.length <= 1}
                      aria-label="Remove row"
                    >
                      ×
                    </button>
                  )}
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

function ModeToggle({
  mode,
  setMode,
}: {
  mode: EntryMode;
  setMode: (m: EntryMode) => void;
}) {
  const base: React.CSSProperties = {
    padding: "6px 14px",
    border: "1px solid var(--border)",
    background: "transparent",
    color: "var(--text-muted)",
    fontSize: 12,
    cursor: "pointer",
  };
  const active: React.CSSProperties = {
    background: "var(--accent)",
    color: "var(--bg)",
    borderColor: "var(--accent)",
  };
  return (
    <div style={{ display: "inline-flex", borderRadius: 6, overflow: "hidden" }}>
      <button
        type="button"
        style={{
          ...base,
          ...(mode === "live" ? active : {}),
          borderRadius: "6px 0 0 6px",
          borderRight: "none",
        }}
        onClick={() => setMode("live")}
        title="Tap 'Log set' between reps to stamp each set with a timestamp — enables per-set HR."
      >
        Live
      </button>
      <button
        type="button"
        style={{
          ...base,
          ...(mode === "retro" ? active : {}),
          borderRadius: "0 6px 6px 0",
        }}
        onClick={() => setMode("retro")}
        title="Batch-enter all sets at once. No per-set HR but saves without live taps."
      >
        Retro
      </button>
    </div>
  );
}

function RestTimerChip({ seconds }: { seconds: number | null }) {
  if (seconds == null) {
    return (
      <span
        className="chip"
        style={{ fontSize: 12, color: "var(--text-muted)" }}
        title="Tap 'Log set' on the first row to start the rest timer"
      >
        Rest: —
      </span>
    );
  }
  const color = seconds < 60 ? "var(--text-muted)" : "var(--accent)";
  return (
    <span
      className="chip"
      style={{ fontSize: 12, color, fontVariantNumeric: "tabular-nums" }}
      title="Time since your last logged set"
    >
      Rest: {formatRestTimer(seconds)}
    </span>
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
