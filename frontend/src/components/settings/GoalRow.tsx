import { useState } from "react";
import {
  deleteGoal,
  patchGoal,
  setPrimaryGoal,
  type Goal,
  type GoalStatus,
} from "../../api/goals";

export default function GoalRow({
  goal,
  onChange,
}: {
  goal: Goal;
  onChange: () => void;
}) {
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
