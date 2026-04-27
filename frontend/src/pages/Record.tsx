import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useApi } from "../hooks/useApi";
import {
  createStrengthSession,
  fetchStrengthExercises,
  type StrengthSetInput,
} from "../api/strength";
import { getErrorMessage } from "../utils/errors";
import { SessionHeader } from "../components/record/SessionHeader";
import { SessionMeta } from "../components/record/SessionMeta";
import { ExerciseCard } from "../components/record/ExerciseCard";
import { toNaiveLocalIso } from "../components/record/datetime";
import type { ExerciseDraft, SetDraft } from "../components/record/types";

let nextKey = 1;
const newKey = () => nextKey++;

const emptySet = (): SetDraft => ({
  key: newKey(),
  weight: "",
  reps: "",
  rpe: "",
  performed_at: null,
});

const emptyExercise = (): ExerciseDraft => ({
  key: newKey(),
  name: "",
  notes: "",
  showNotes: false,
  linkedToNext: false,
  sets: [emptySet(), emptySet(), emptySet()],
});

const containerVariants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.05 } },
};

export default function Record() {
  const navigate = useNavigate();
  const today = new Date().toISOString().slice(0, 10);

  const [date, setDate] = useState(today);
  const [exercises, setExercises] = useState<ExerciseDraft[]>(() => [
    emptyExercise(),
  ]);
  const [isRunning, setIsRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Background data: known exercise names for the <datalist> autocomplete.
  const { data: knownExercises } = useApi(() => fetchStrengthExercises(), []);

  // Workout timer (1 Hz) — runs only while the session is active.
  useEffect(() => {
    if (!isRunning) return;
    const id = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [isRunning]);

  // Rest-timer clock. Cheap; ticks regardless so the rest chip stays live.
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const lastLoggedAt = useMemo(() => {
    let max: number | null = null;
    for (const ex of exercises) {
      for (const s of ex.sets) {
        if (!s.performed_at) continue;
        const t = new Date(s.performed_at).getTime();
        if (max == null || t > max) max = t;
      }
    }
    return max;
  }, [exercises]);
  const restSeconds =
    lastLoggedAt != null
      ? Math.max(0, Math.floor((now - lastLoggedAt) / 1000))
      : null;

  const hasStarted = isRunning || elapsed > 0;
  const hasLoggedSet = lastLoggedAt != null;

  const autoStartIfIdle = (next: ExerciseDraft[]) => {
    if (isRunning || elapsed !== 0) return;
    const dirty = next.some(
      (ex) =>
        ex.name.trim() !== "" ||
        ex.sets.some((s) => s.weight !== "" || s.reps !== "")
    );
    if (dirty) setIsRunning(true);
  };

  const updateExercises = (
    updater: (draft: ExerciseDraft[]) => ExerciseDraft[]
  ) => {
    setExercises((prev) => {
      const next = updater(prev);
      autoStartIfIdle(next);
      return next;
    });
  };

  const updateExercise = (key: number, patch: Partial<ExerciseDraft>) =>
    updateExercises((prev) =>
      prev.map((ex) => (ex.key === key ? { ...ex, ...patch } : ex))
    );

  const addExercise = () =>
    setExercises((prev) => [...prev, emptyExercise()]);

  const toggleLinkNext = (index: number) =>
    setExercises((prev) =>
      prev.map((ex, i) =>
        i === index ? { ...ex, linkedToNext: !ex.linkedToNext } : ex
      )
    );

  const updateSetField = (
    exerciseKey: number,
    setKey: number,
    field: "weight" | "reps" | "rpe",
    value: string
  ) =>
    updateExercises((prev) =>
      prev.map((ex) => {
        if (ex.key !== exerciseKey) return ex;
        const idx = ex.sets.findIndex((s) => s.key === setKey);
        if (idx < 0) return ex;
        const sets = [...ex.sets];
        const oldValue = sets[idx][field];
        sets[idx] = { ...sets[idx], [field]: value };
        // Cascade to subsequent empty / matching-old-value rows so users
        // don't retype the same weight on every set.
        for (let i = idx + 1; i < sets.length; i++) {
          if (sets[i][field] === oldValue || sets[i][field] === "") {
            sets[i] = { ...sets[i], [field]: value };
          } else {
            break;
          }
        }
        return { ...ex, sets };
      })
    );

  const toggleSetComplete = (exerciseKey: number, setKey: number) => {
    setExercises((prev) =>
      prev.map((ex) => {
        if (ex.key !== exerciseKey) return ex;
        const idx = ex.sets.findIndex((s) => s.key === setKey);
        if (idx < 0) return ex;
        const set = ex.sets[idx];
        const isLast = idx === ex.sets.length - 1;

        // Untoggle: clear the timestamp.
        if (set.performed_at) {
          const sets = ex.sets.map((s, i) =>
            i === idx ? { ...s, performed_at: null } : s
          );
          return { ...ex, sets };
        }

        // Stamp: must have at least reps filled in (matches today's Live).
        if (set.reps === "" || Number(set.reps) < 1) {
          setError("Fill in reps before logging this set.");
          return ex;
        }
        if (!ex.name.trim()) {
          setError("Name the exercise before logging a set.");
          return ex;
        }
        setError(null);
        const stamped = { ...set, performed_at: toNaiveLocalIso(new Date()) };
        const sets = ex.sets.map((s, i) => (i === idx ? stamped : s));
        // Auto-append a fresh row if this was the last set in the card.
        if (isLast) sets.push(emptySet());
        // Auto-start the workout timer if a set was just logged.
        if (!isRunning && elapsed === 0) setIsRunning(true);
        return { ...ex, sets };
      })
    );
  };

  const addSet = (exerciseKey: number) =>
    updateExercises((prev) =>
      prev.map((ex) => {
        if (ex.key !== exerciseKey) return ex;
        const last = ex.sets[ex.sets.length - 1];
        const seed = last
          ? { ...emptySet(), weight: last.weight, reps: last.reps, rpe: last.rpe }
          : emptySet();
        return { ...ex, sets: [...ex.sets, seed] };
      })
    );

  const handleStart = () => setIsRunning(true);
  const handlePause = () => setIsRunning(false);

  const canFinish = hasLoggedSet && !saving;

  const handleFinish = async () => {
    setSaving(true);
    setError(null);
    try {
      const payload: StrengthSetInput[] = exercises.flatMap((ex) => {
        const name = ex.name.trim();
        if (!name) return [];
        const logged = ex.sets.filter((s) => s.performed_at != null);
        return logged.map((s, idx) => ({
          exercise_name: name,
          set_number: idx + 1,
          reps: Number(s.reps),
          weight_kg: s.weight === "" ? null : Number(s.weight),
          rpe: s.rpe === "" ? null : Number(s.rpe),
          notes: ex.notes.trim() === "" ? null : ex.notes.trim(),
          performed_at: s.performed_at,
        }));
      });
      if (payload.length === 0) {
        setError("Log at least one set before finishing.");
        setSaving(false);
        return;
      }
      await createStrengthSession({ date, activity_id: null, sets: payload });
      setIsRunning(false);
      navigate("/history");
    } catch (e) {
      setError(getErrorMessage(e, "Failed to save session"));
      setSaving(false);
    }
  };

  return (
    <div className="pb-4 pt-2">
      <SessionHeader
        elapsed={elapsed}
        isRunning={isRunning}
        hasStarted={hasStarted}
        canFinish={canFinish}
        finishLabel={saving ? "Saving…" : "Finish"}
        onStart={handleStart}
        onPause={handlePause}
        onFinish={handleFinish}
      />

      <SessionMeta date={date} onDateChange={setDate} restSeconds={restSeconds} />

      {error && (
        <div
          role="alert"
          className="mb-2 px-3 py-2 rounded-md bg-brand-red/10 border border-brand-red/40 text-xs text-brand-red"
        >
          {error}
        </div>
      )}

      {/* Page-wide datalist used by every ExerciseCard's name input. */}
      <datalist id="exercise-list">
        {knownExercises?.map((ex) => (
          <option key={ex} value={ex} />
        ))}
      </datalist>

      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="flex flex-col"
      >
        {exercises.map((ex, index) => (
          <ExerciseCard
            key={ex.key}
            exercise={ex}
            isLinkedToPrev={index > 0 && exercises[index - 1].linkedToNext}
            isLinkedToNext={ex.linkedToNext}
            showLinkButton={index < exercises.length - 1}
            onNameChange={(name) => updateExercise(ex.key, { name })}
            onToggleNotes={() =>
              updateExercise(ex.key, { showNotes: !ex.showNotes })
            }
            onNotesChange={(notes) => updateExercise(ex.key, { notes })}
            onUpdateSetField={(setKey, field, value) =>
              updateSetField(ex.key, setKey, field, value)
            }
            onToggleComplete={(setKey) => toggleSetComplete(ex.key, setKey)}
            onAddSet={() => addSet(ex.key)}
            onToggleLinkNext={() => toggleLinkNext(index)}
          />
        ))}
      </motion.div>

      <button
        type="button"
        onClick={addExercise}
        className="w-full mt-2 py-2 border border-dashed border-cardBorder rounded-lg flex items-center justify-center gap-1.5 text-slate-400 hover:text-white hover:border-slate-500 hover:bg-cardBorder/20 transition-all"
      >
        <span className="text-sm">+</span>
        <span className="font-medium text-xs">Add Exercise</span>
      </button>
    </div>
  );
}
