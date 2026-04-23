import { useEffect, useState } from "react";
import {
  createGoal,
  deleteGoal,
  listGoals,
  patchGoal,
  setPrimaryGoal,
  type Goal,
  type GoalStatus,
} from "../api/goals";

/**
 * Training goals CRUD. Lives above UserLocations on the Settings page.
 * The daily recommendation uses the primary goal (at most one) to
 * periodize its intensity guidance.
 */
export default function GoalsSection() {
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    try {
      const rows = await listGoals();
      setGoals(rows);
    } catch (e) {
      setError(extractMessage(e));
    }
  };

  useEffect(() => {
    reload();
  }, []);

  return (
    <>
      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <h2 style={{ marginTop: 0 }}>Add a goal</h2>
        <AddGoal onAdded={reload} />
      </div>

      <div className="card" style={{ padding: 0, marginBottom: 16 }}>
        <h2 style={{ padding: "20px 24px 12px" }}>Goals</h2>
        {error && (
          <div className="error" style={{ margin: "0 24px 12px" }}>
            {error}
          </div>
        )}
        {!goals && <div className="loading">Loading…</div>}
        {goals && goals.length === 0 && (
          <div style={{ padding: "0 24px 20px", color: "var(--text-muted)" }}>
            No goals yet. Add one above so the daily recommendation can
            periodize toward it.
          </div>
        )}
        {goals && goals.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Race</th>
                <th>Target date</th>
                <th>Weeks away</th>
                <th>Status</th>
                <th>Primary</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {goals.map((g) => (
                <GoalRow key={g.id} goal={g} onChange={reload} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

// ── Row ───────────────────────────────────────────────────────────────

function GoalRow({ goal, onChange }: { goal: Goal; onChange: () => void }) {
  const [busy, setBusy] = useState(false);

  const weeksAway = Math.max(
    0,
    Math.round(
      (new Date(goal.target_date).getTime() - Date.now()) /
        (1000 * 60 * 60 * 24 * 7)
    )
  );

  const remove = async () => {
    if (!confirm(`Delete goal "${goal.race_type}"?`)) return;
    setBusy(true);
    try {
      await deleteGoal(goal.id);
      onChange();
    } finally {
      setBusy(false);
    }
  };

  const makePrimary = async () => {
    setBusy(true);
    try {
      await setPrimaryGoal(goal.id);
      onChange();
    } finally {
      setBusy(false);
    }
  };

  const changeStatus = async (status: GoalStatus) => {
    setBusy(true);
    try {
      await patchGoal(goal.id, { status });
      onChange();
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr>
      <td>
        <strong>{goal.race_type}</strong>
        {goal.description && (
          <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
            {goal.description}
          </div>
        )}
      </td>
      <td>{goal.target_date}</td>
      <td style={{ color: "var(--text-muted)" }}>{weeksAway}w</td>
      <td>
        <select
          value={goal.status}
          disabled={busy}
          onChange={(e) => changeStatus(e.target.value as GoalStatus)}
        >
          <option value="active">active</option>
          <option value="completed">completed</option>
          <option value="abandoned">abandoned</option>
        </select>
      </td>
      <td>
        {goal.is_primary ? (
          <span className="chip">primary</span>
        ) : (
          <button className="btn btn-ghost" disabled={busy} onClick={makePrimary}>
            Make primary
          </button>
        )}
      </td>
      <td>
        <button className="btn btn-ghost" disabled={busy} onClick={remove}>
          Delete
        </button>
      </td>
    </tr>
  );
}

// ── Add goal form ─────────────────────────────────────────────────────

function AddGoal({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [raceType, setRaceType] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [description, setDescription] = useState("");
  const [isPrimary, setIsPrimary] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setRaceType("");
    setTargetDate("");
    setDescription("");
    setIsPrimary(true);
    setError(null);
  };

  const submit = async () => {
    if (!raceType.trim() || !targetDate) return;
    setBusy(true);
    setError(null);
    try {
      await createGoal({
        race_type: raceType.trim(),
        target_date: targetDate,
        description: description.trim() || null,
        is_primary: isPrimary,
      });
      reset();
      setOpen(false);
      onAdded();
    } catch (e) {
      setError(extractMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button className="btn" onClick={() => setOpen(true)}>
        New goal
      </button>
    );
  }

  return (
    <div style={{ display: "grid", gap: 8, maxWidth: 420 }}>
      <input
        autoFocus
        placeholder="Race type (e.g. Marathon, Half-Ironman, 10k)"
        value={raceType}
        onChange={(e) => setRaceType(e.target.value)}
      />
      <input
        type="date"
        value={targetDate}
        onChange={(e) => setTargetDate(e.target.value)}
      />
      <textarea
        placeholder="Notes (optional): course, goal time, priority …"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        rows={2}
      />
      <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <input
          type="checkbox"
          checked={isPrimary}
          onChange={(e) => setIsPrimary(e.target.checked)}
        />
        Make primary goal
      </label>
      {error && <div className="error">{error}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          className="btn"
          disabled={busy || !raceType.trim() || !targetDate}
          onClick={submit}
        >
          Save
        </button>
        <button
          className="btn btn-ghost"
          onClick={() => {
            reset();
            setOpen(false);
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function extractMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}
