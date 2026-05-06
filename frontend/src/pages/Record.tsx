import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useApi } from "../hooks/useApi";
import { invalidateAppDataQueries } from "../lib/queryCache";
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
const DRAFT_STORAGE_KEY = "health-tracker:record-draft:v1";

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

type RecordDraft = {
  version: 1;
  date: string;
  exercises: ExerciseDraft[];
  isRunning: boolean;
  elapsed: number;
  savedAt: number;
};

type InitialRecordDraft = Omit<RecordDraft, "version" | "savedAt">;

function loadRecordDraft(today: string): InitialRecordDraft {
  const fallback = {
    date: today,
    exercises: [emptyExercise()],
    isRunning: false,
    elapsed: 0,
  };
  try {
    const raw = window.localStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<RecordDraft>;
    if (parsed.version !== 1 || !Array.isArray(parsed.exercises)) {
      return fallback;
    }
    const exercises = normalizeExercises(parsed.exercises);
    const savedAt = readNonNegativeNumber(parsed.savedAt) ?? Date.now();
    const wasRunning = parsed.isRunning === true;
    const storedElapsed = readNonNegativeNumber(parsed.elapsed) ?? 0;
    const elapsed = wasRunning
      ? storedElapsed + Math.max(0, Math.floor((Date.now() - savedAt) / 1000))
      : storedElapsed;
    return {
      date: typeof parsed.date === "string" && parsed.date ? parsed.date : today,
      exercises,
      isRunning: wasRunning,
      elapsed,
    };
  } catch {
    return fallback;
  }
}

function saveRecordDraft(draft: InitialRecordDraft) {
  try {
    const snapshot: RecordDraft = {
      version: 1,
      ...draft,
      savedAt: Date.now(),
    };
    window.localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(snapshot));
  } catch {
    // localStorage can be unavailable in private/locked-down contexts.
  }
}

function clearRecordDraft() {
  try {
    window.localStorage.removeItem(DRAFT_STORAGE_KEY);
  } catch {
    // Best effort only.
  }
}

function normalizeExercises(value: unknown[]): ExerciseDraft[] {
  const exercises = value
    .map((item) => normalizeExercise(item))
    .filter((item): item is ExerciseDraft => item != null);
  if (exercises.length === 0) return [emptyExercise()];

  const maxKey = exercises.reduce((max, ex) => {
    const setMax = ex.sets.reduce((innerMax, s) => Math.max(innerMax, s.key), 0);
    return Math.max(max, ex.key, setMax);
  }, 0);
  if (maxKey >= nextKey) nextKey = maxKey + 1;
  return exercises;
}

function normalizeExercise(value: unknown): ExerciseDraft | null {
  if (value == null || typeof value !== "object") return null;
  const raw = value as Partial<ExerciseDraft>;
  const sets = Array.isArray(raw.sets)
    ? raw.sets
        .map((item) => normalizeSet(item))
        .filter((item): item is SetDraft => item != null)
    : [];
  return {
    key: readPositiveInteger(raw.key) ?? newKey(),
    name: typeof raw.name === "string" ? raw.name : "",
    notes: typeof raw.notes === "string" ? raw.notes : "",
    showNotes: raw.showNotes === true,
    linkedToNext: raw.linkedToNext === true,
    sets: sets.length > 0 ? sets : [emptySet(), emptySet(), emptySet()],
  };
}

function normalizeSet(value: unknown): SetDraft | null {
  if (value == null || typeof value !== "object") return null;
  const raw = value as Partial<SetDraft>;
  return {
    key: readPositiveInteger(raw.key) ?? newKey(),
    weight: typeof raw.weight === "string" ? raw.weight : "",
    reps: typeof raw.reps === "string" ? raw.reps : "",
    rpe: typeof raw.rpe === "string" ? raw.rpe : "",
    performed_at:
      typeof raw.performed_at === "string" && raw.performed_at
        ? raw.performed_at
        : null,
  };
}

function readPositiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : null;
}

function readNonNegativeNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : null;
}

function parseRequiredReps(value: string): number | null {
  const reps = Number(value);
  if (!Number.isInteger(reps) || reps < 1) return null;
  return reps;
}

function parseOptionalNonNegative(value: string): number | null | undefined {
  if (value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return undefined;
  return number;
}

function parseOptionalRpe(value: string): number | null | undefined {
  const rpe = parseOptionalNonNegative(value);
  if (rpe == null) return rpe;
  if (rpe > 10) return undefined;
  return rpe;
}

function validateSetForLogging(set: SetDraft): string | null {
  if (parseRequiredReps(set.reps) == null) {
    return "Fill in whole-number reps before logging this set.";
  }
  if (parseOptionalNonNegative(set.weight) === undefined) {
    return "Weight must be a non-negative number.";
  }
  if (parseOptionalRpe(set.rpe) === undefined) {
    return "RPE must be between 0 and 10.";
  }
  return null;
}

function buildPayload(exercises: ExerciseDraft[]): StrengthSetInput[] | string {
  const payload: StrengthSetInput[] = [];
  for (const ex of exercises) {
    const name = ex.name.trim();
    if (!name) continue;
    const logged = ex.sets.filter((s) => s.performed_at != null);
    for (const [idx, set] of logged.entries()) {
      const reps = parseRequiredReps(set.reps);
      const weight = parseOptionalNonNegative(set.weight);
      const rpe = parseOptionalRpe(set.rpe);
      if (reps == null) return `${name} set ${idx + 1} needs whole-number reps.`;
      if (weight === undefined) {
        return `${name} set ${idx + 1} has an invalid weight.`;
      }
      if (rpe === undefined) {
        return `${name} set ${idx + 1} has an invalid RPE.`;
      }
      payload.push({
        exercise_name: name,
        set_number: idx + 1,
        reps,
        weight_kg: weight,
        rpe,
        notes: ex.notes.trim() === "" ? null : ex.notes.trim(),
        performed_at: set.performed_at,
      });
    }
  }
  return payload;
}

export default function Record() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const [initialDraft] = useState(() => loadRecordDraft(today));

  const [date, setDate] = useState(initialDraft.date);
  const [exercises, setExercises] = useState<ExerciseDraft[]>(
    initialDraft.exercises,
  );
  const [isRunning, setIsRunning] = useState(initialDraft.isRunning);
  const [elapsed, setElapsed] = useState(initialDraft.elapsed);
  const [now, setNow] = useState(() => Date.now());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Background data: known exercise names for the <datalist> autocomplete.
  const { data: knownExercises } = useApi(["strength", "exercises"], () =>
    fetchStrengthExercises(),
  );

  useEffect(() => {
    saveRecordDraft({ date, exercises, isRunning, elapsed });
  }, [date, elapsed, exercises, isRunning]);

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

        // Stamp: validate client-side so malformed number inputs never reach the API.
        const validationError = validateSetForLogging(set);
        if (validationError) {
          setError(validationError);
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
      const payload = buildPayload(exercises);
      if (typeof payload === "string") {
        setError(payload);
        setSaving(false);
        return;
      }
      if (payload.length === 0) {
        setError("Log at least one set before finishing.");
        setSaving(false);
        return;
      }
      await createStrengthSession({ date, activity_id: null, sets: payload });
      clearRecordDraft();
      void invalidateAppDataQueries(queryClient);
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
