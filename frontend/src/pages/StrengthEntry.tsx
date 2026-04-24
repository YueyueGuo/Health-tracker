import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import {
  createStrengthSession,
  fetchStrengthExercises,
  fetchStrengthProgression,
  type ProgressionPoint,
  type StrengthSetInput,
} from "../api/strength";
import { fetchActivities, type ActivitySummary } from "../api/activities";
import { getErrorMessage } from "../utils/errors";

/**
 * Log a strength session as a list of exercise cards. Two entry modes:
 *
 *   * **Live** (default) — tap "Log" between reps. Each tap stamps
 *     `performed_at` on that set and auto-adds a fresh set to the same
 *     card. A rest-timer chip shows seconds since the most recent log.
 *     Only stamped sets are saved.
 *   * **Retro** — classic form. No timestamps; every set with reps ≥ 1
 *     saves. `performed_at` is stripped to null.
 *
 * Set numbers are generated from card order on save, so the existing
 * backend contract (`set_number` required) is unchanged.
 */

type EntryMode = "live" | "retro";

type SetDraft = {
  key: number;
  reps: number | "";
  weight_kg: number | "";
  rpe: number | "";
  notes: string;
  /** Naive-local ISO string stamped by Live-mode "Log" tap. Null until logged. */
  performed_at: string | null;
};

type ExerciseCard = {
  key: number;
  name: string;
  sets: SetDraft[];
};

let nextKey = 1;
const newKey = () => nextKey++;

const emptySet = (): SetDraft => ({
  key: newKey(),
  reps: "",
  weight_kg: "",
  rpe: "",
  notes: "",
  performed_at: null,
});

const emptyCard = (name = ""): ExerciseCard => ({
  key: newKey(),
  name,
  sets: [emptySet()],
});

/** `new Date()` → "YYYY-MM-DDTHH:mm:ss" (naive local wall clock, no tz).
 *  Matches the Eight Sleep convention used for sleep + activity
 *  timestamps throughout the codebase. */
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
  const [cards, setCards] = useState<ExerciseCard[]>(() => [emptyCard()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const { data: exercises } = useApi(() => fetchStrengthExercises(), []);
  const { data: activities } = useApi(
    () => fetchActivities({ sport_type: "WeightTraining", days: 30, limit: 20 }),
    []
  );

  // Rest timer: 1 Hz tick while in live mode. Cheap; ticks pause in retro.
  useEffect(() => {
    if (mode !== "live") return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [mode]);

  const lastLoggedAt = useMemo(() => {
    let max: number | null = null;
    for (const c of cards) {
      for (const s of c.sets) {
        if (!s.performed_at) continue;
        const t = new Date(s.performed_at).getTime();
        if (max == null || t > max) max = t;
      }
    }
    return max;
  }, [cards]);
  const restSeconds =
    lastLoggedAt != null ? Math.max(0, Math.floor((now - lastLoggedAt) / 1000)) : null;

  // After a Log tap that appends a fresh set, focus the new set's reps
  // input so the user can start typing immediately.
  const repsRefs = useRef<Map<number, HTMLInputElement | null>>(new Map());
  const pendingFocusKey = useRef<number | null>(null);
  useEffect(() => {
    const key = pendingFocusKey.current;
    if (key == null) return;
    const el = repsRefs.current.get(key);
    if (el) {
      el.focus();
      pendingFocusKey.current = null;
    }
  }, [cards]);

  const updateCard = (key: number, patch: Partial<ExerciseCard>) =>
    setCards((cs) => cs.map((c) => (c.key === key ? { ...c, ...patch } : c)));

  const updateSet = (cardKey: number, setKey: number, patch: Partial<SetDraft>) =>
    setCards((cs) =>
      cs.map((c) =>
        c.key === cardKey
          ? { ...c, sets: c.sets.map((s) => (s.key === setKey ? { ...s, ...patch } : s)) }
          : c
      )
    );

  const addSet = (cardKey: number) => {
    const freshKey = newKey();
    setCards((cs) =>
      cs.map((c) =>
        c.key === cardKey
          ? { ...c, sets: [...c.sets, { ...emptySet(), key: freshKey }] }
          : c
      )
    );
    return freshKey;
  };

  const removeSet = (cardKey: number, setKey: number) =>
    setCards((cs) =>
      cs.map((c) =>
        c.key === cardKey && c.sets.length > 1
          ? { ...c, sets: c.sets.filter((s) => s.key !== setKey) }
          : c
      )
    );

  const addCard = () => setCards((cs) => [...cs, emptyCard()]);

  const removeCard = (key: number) =>
    setCards((cs) => (cs.length > 1 ? cs.filter((c) => c.key !== key) : cs));

  const logSet = (cardKey: number, setKey: number) => {
    const card = cards.find((c) => c.key === cardKey);
    const set = card?.sets.find((s) => s.key === setKey);
    if (!card || !set) return;
    if (!card.name.trim()) {
      setError("Name the exercise before logging a set.");
      return;
    }
    if (set.reps === "" || Number(set.reps) < 1) {
      setError("Fill in reps before logging this set.");
      return;
    }
    setError(null);
    updateSet(cardKey, setKey, { performed_at: toNaiveLocalIso(new Date()) });
    // Auto-append and focus only if this was the last set in its card.
    const isLast = card.sets[card.sets.length - 1].key === setKey;
    if (isLast) {
      pendingFocusKey.current = addSet(cardKey);
    }
  };

  const canSave = useMemo(() => {
    if (cards.every((c) => !c.name.trim())) return false;
    if (mode === "live") {
      return cards.some((c) => c.sets.some((s) => s.performed_at != null));
    }
    return cards.every(
      (c) =>
        c.name.trim().length > 0 &&
        c.sets.length > 0 &&
        c.sets.every((s) => s.reps !== "" && Number(s.reps) >= 1)
    );
  }, [cards, mode]);

  const handleSave = async () => {
    setError(null);
    setSaving(true);
    try {
      const payload: StrengthSetInput[] = cards.flatMap((card) => {
        const name = card.name.trim();
        if (!name) return [];
        const sourceSets =
          mode === "live" ? card.sets.filter((s) => s.performed_at != null) : card.sets;
        return sourceSets.map((s, idx) => ({
          exercise_name: name,
          set_number: idx + 1,
          reps: Number(s.reps),
          weight_kg: s.weight_kg === "" ? null : Number(s.weight_kg),
          rpe: s.rpe === "" ? null : Number(s.rpe),
          notes: s.notes.trim() === "" ? null : s.notes.trim(),
          performed_at: mode === "live" ? s.performed_at : null,
        }));
      });
      await createStrengthSession({ date, activity_id: activityId, sets: payload });
      navigate("/strength");
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Failed to save session"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Log Strength Session</h1>
        <p>
          {mode === "live"
            ? "Tap “Log” between sets to stamp timing and keep the rest timer honest."
            : "Enter completed sets after the fact — no timestamps saved."}{" "}
          <Link to="/strength">← Back to sessions</Link>
        </p>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <div className="filter-bar" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field">
            <span className="field-label">Mode</span>
            <ModeToggle mode={mode} onChange={setMode} />
          </label>
          <label className="field">
            <span className="field-label">Date</span>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="input"
            />
          </label>
          <label className="field" style={{ minWidth: 260 }}>
            <span className="field-label">Link Strava activity (optional)</span>
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
            <div className="rest-timer" aria-live="polite">
              <span className="field-label">Rest</span>
              <span className="rest-timer-value">
                {restSeconds != null ? formatRestTimer(restSeconds) : "—"}
              </span>
            </div>
          )}
        </div>
      </div>

      <datalist id="exercise-list">
        {exercises?.map((ex) => (
          <option key={ex} value={ex} />
        ))}
      </datalist>

      {cards.map((card, idx) => (
        <ExerciseCardView
          key={card.key}
          card={card}
          mode={mode}
          canRemoveCard={cards.length > 1}
          onNameChange={(name) => updateCard(card.key, { name })}
          onRemoveCard={() => removeCard(card.key)}
          onAddSet={() => addSet(card.key)}
          onRemoveSet={(setKey) => removeSet(card.key, setKey)}
          onUpdateSet={(setKey, patch) => updateSet(card.key, setKey, patch)}
          onLogSet={(setKey) => logSet(card.key, setKey)}
          registerRepsInput={(setKey, el) => {
            if (el) repsRefs.current.set(setKey, el);
            else repsRefs.current.delete(setKey);
          }}
          index={idx}
        />
      ))}

      <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap" }}>
        <button type="button" className="btn btn-secondary" onClick={addCard}>
          + Add exercise
        </button>
        <button
          type="button"
          className="btn"
          onClick={handleSave}
          disabled={!canSave || saving}
        >
          {saving ? "Saving..." : "Save session"}
        </button>
        <Link
          to="/strength"
          className="btn btn-secondary"
          style={{ textDecoration: "none" }}
        >
          Cancel
        </Link>
      </div>
    </div>
  );
}

function ModeToggle({
  mode,
  onChange,
}: {
  mode: EntryMode;
  onChange: (m: EntryMode) => void;
}) {
  return (
    <div className="mode-toggle" role="radiogroup" aria-label="Entry mode">
      <button
        type="button"
        role="radio"
        aria-checked={mode === "live"}
        className={`mode-toggle-btn${mode === "live" ? " is-active" : ""}`}
        onClick={() => onChange("live")}
      >
        Live
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={mode === "retro"}
        className={`mode-toggle-btn${mode === "retro" ? " is-active" : ""}`}
        onClick={() => onChange("retro")}
      >
        Retro
      </button>
    </div>
  );
}

function ExerciseCardView({
  card,
  mode,
  canRemoveCard,
  onNameChange,
  onRemoveCard,
  onAddSet,
  onRemoveSet,
  onUpdateSet,
  onLogSet,
  registerRepsInput,
  index,
}: {
  card: ExerciseCard;
  mode: EntryMode;
  canRemoveCard: boolean;
  onNameChange: (name: string) => void;
  onRemoveCard: () => void;
  onAddSet: () => void;
  onRemoveSet: (setKey: number) => void;
  onUpdateSet: (setKey: number, patch: Partial<SetDraft>) => void;
  onLogSet: (setKey: number) => void;
  registerRepsInput: (setKey: number, el: HTMLInputElement | null) => void;
  index: number;
}) {
  const priorLabel = usePriorPerformance(card.name);

  return (
    <div className="card exercise-card">
      <div className="exercise-card-header">
        <input
          className="input exercise-name-input"
          list="exercise-list"
          placeholder={index === 0 ? "Exercise (e.g. Squat)" : "Exercise"}
          value={card.name}
          aria-label="Exercise name"
          onChange={(e) => onNameChange(e.target.value)}
        />
        <button
          type="button"
          className="link-btn"
          onClick={onRemoveCard}
          disabled={!canRemoveCard}
          aria-label="Remove exercise"
        >
          ×
        </button>
      </div>
      {priorLabel && <div className="prior-perf">{priorLabel}</div>}

      <table className="data-table data-table-compact set-table">
        <thead>
          <tr>
            <th style={{ width: 44 }}>Set</th>
            <th style={{ width: 140 }}>Reps</th>
            <th style={{ width: 180 }}>Weight (kg)</th>
            <th style={{ width: 70 }}>RPE</th>
            <th>Notes</th>
            {mode === "live" && <th style={{ width: 96 }}>Log</th>}
            <th style={{ width: 40 }}></th>
          </tr>
        </thead>
        <tbody>
          {card.sets.map((set, setIdx) => (
            <tr
              key={set.key}
              className={set.performed_at ? "set-logged" : undefined}
              style={{ cursor: "default" }}
            >
              <td className="set-number">{setIdx + 1}</td>
              <td>
                <Stepper
                  value={set.reps}
                  step={1}
                  min={1}
                  ariaLabel="Reps"
                  inputRef={(el) => registerRepsInput(set.key, el)}
                  onChange={(v) => onUpdateSet(set.key, { reps: v })}
                />
              </td>
              <td>
                <Stepper
                  value={set.weight_kg}
                  step={2.5}
                  min={0}
                  ariaLabel="Weight"
                  onChange={(v) => onUpdateSet(set.key, { weight_kg: v })}
                />
              </td>
              <td>
                <input
                  className="input"
                  type="number"
                  min={0}
                  max={10}
                  step="0.5"
                  value={set.rpe}
                  onChange={(e) =>
                    onUpdateSet(set.key, {
                      rpe: e.target.value === "" ? "" : Number(e.target.value),
                    })
                  }
                />
              </td>
              <td>
                <input
                  className="input"
                  type="text"
                  value={set.notes}
                  onChange={(e) => onUpdateSet(set.key, { notes: e.target.value })}
                />
              </td>
              {mode === "live" && (
                <td>
                  {set.performed_at ? (
                    <span className="log-stamp" aria-label={`Logged at ${formatClockTime(set.performed_at)}`}>
                      ✓ {formatClockTime(set.performed_at)}
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-secondary log-btn"
                      onClick={() => onLogSet(set.key)}
                    >
                      Log
                    </button>
                  )}
                </td>
              )}
              <td style={{ textAlign: "right" }}>
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => onRemoveSet(set.key)}
                  disabled={card.sets.length <= 1}
                  aria-label="Remove set"
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <button
        type="button"
        className="btn btn-secondary"
        style={{ marginTop: 12 }}
        onClick={onAddSet}
      >
        + Add set
      </button>
    </div>
  );
}

function Stepper({
  value,
  step,
  min,
  ariaLabel,
  inputRef,
  onChange,
}: {
  value: number | "";
  step: number;
  min: number;
  ariaLabel: string;
  inputRef?: (el: HTMLInputElement | null) => void;
  onChange: (v: number | "") => void;
}) {
  const current = value === "" ? null : Number(value);
  const decrement = () => {
    const next = current == null ? min : current - step;
    onChange(Math.max(min, Number(next.toFixed(2))));
  };
  const increment = () => {
    // Empty input: jump to the first non-trivial value the user likely
    // wants (e.g. 1 rep or 2.5 kg), not to a literal min of 0.
    const next = current == null ? Math.max(min, step) : current + step;
    onChange(Number(next.toFixed(2)));
  };
  return (
    <div className="stepper">
      <button
        type="button"
        className="stepper-btn"
        onClick={decrement}
        aria-label={`Decrease ${ariaLabel}`}
      >
        −
      </button>
      <input
        ref={inputRef}
        className="input stepper-input"
        type="number"
        step={step}
        min={min}
        aria-label={ariaLabel}
        value={value}
        onChange={(e) =>
          onChange(e.target.value === "" ? "" : Number(e.target.value))
        }
      />
      <button
        type="button"
        className="stepper-btn"
        onClick={increment}
        aria-label={`Increase ${ariaLabel}`}
      >
        +
      </button>
    </div>
  );
}

/** Returns a muted-text label summarising the last recorded session for
 *  an exercise, or null until a known name is entered. Debounced to
 *  avoid firing a request on every keystroke. */
function usePriorPerformance(name: string): string | null {
  const trimmed = name.trim();
  const [point, setPoint] = useState<ProgressionPoint | null>(null);
  const [lookedUpName, setLookedUpName] = useState<string | null>(null);

  useEffect(() => {
    if (!trimmed) {
      setPoint(null);
      setLookedUpName(null);
      return;
    }
    if (trimmed === lookedUpName) return;
    let cancelled = false;
    const handle = window.setTimeout(async () => {
      try {
        const history = await fetchStrengthProgression(trimmed, 180);
        if (cancelled) return;
        setPoint(history.length > 0 ? history[history.length - 1] : null);
        setLookedUpName(trimmed);
      } catch {
        if (cancelled) return;
        setPoint(null);
        setLookedUpName(trimmed);
      }
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [trimmed, lookedUpName]);

  if (!point || lookedUpName !== trimmed) return null;
  const weight = point.max_weight_kg > 0 ? ` @ ${point.max_weight_kg} kg` : "";
  const oneRm =
    point.est_1rm_kg > 0 ? ` · est 1RM ${point.est_1rm_kg.toFixed(1)} kg` : "";
  return `Last (${formatShortDate(point.date)}): top set ${point.top_set_reps} reps${weight}${oneRm}`;
}

function formatShortDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function activityLabel(a: ActivitySummary): string {
  const d = a.start_date_local || a.start_date;
  const datePart = d
    ? new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : "";
  const mins = a.moving_time ? Math.round(a.moving_time / 60) : null;
  return `${datePart} · ${a.name}${mins != null ? ` (${mins}m)` : ""}`;
}
