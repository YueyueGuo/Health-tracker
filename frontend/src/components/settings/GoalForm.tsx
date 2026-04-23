import { useState } from "react";
import { createGoal } from "../../api/goals";
import { getErrorMessage } from "../../utils/errors";

export default function GoalForm({ onAdded }: { onAdded: () => void }) {
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
    } catch (error) {
      setError(getErrorMessage(error));
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
