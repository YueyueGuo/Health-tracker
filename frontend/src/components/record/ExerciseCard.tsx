import { Check, Link as LinkIcon, MessageSquare, Plus, Unlink } from "lucide-react";
import { Card } from "../ui/Card";
import { usePriorPerformance } from "./usePriorPerformance";
import type { ExerciseDraft, SetDraft } from "./types";

type SetField = "weight" | "reps" | "rpe";

interface Props {
  exercise: ExerciseDraft;
  isLinkedToPrev: boolean;
  isLinkedToNext: boolean;
  showLinkButton: boolean;
  onNameChange: (name: string) => void;
  onToggleNotes: () => void;
  onNotesChange: (notes: string) => void;
  onUpdateSetField: (setKey: number, field: SetField, value: string) => void;
  onToggleComplete: (setKey: number) => void;
  onAddSet: () => void;
  onToggleLinkNext: () => void;
}

export function ExerciseCard({
  exercise,
  isLinkedToPrev,
  isLinkedToNext,
  showLinkButton,
  onNameChange,
  onToggleNotes,
  onNotesChange,
  onUpdateSetField,
  onToggleComplete,
  onAddSet,
  onToggleLinkNext,
}: Props) {
  const priorLabel = usePriorPerformance(exercise.name);
  const linkClasses = [
    isLinkedToPrev ? "rounded-t-none border-t-0" : "",
    isLinkedToNext ? "rounded-b-none mb-0" : "mb-2",
    isLinkedToPrev || isLinkedToNext ? "border-l-2 border-l-brand-green" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="relative flex flex-col">
      <Card className={`!p-0 overflow-hidden transition-all duration-200 ${linkClasses}`}>
        {/* Header: name input + notes toggle */}
        <div className="px-2 pt-1 pb-1.5 border-b border-cardBorder bg-cardBorder/20 flex items-center gap-2">
          <input
            type="text"
            placeholder="Exercise Name"
            value={exercise.name}
            onChange={(e) => onNameChange(e.target.value)}
            list="exercise-list"
            aria-label="Exercise name"
            className="flex-1 bg-transparent text-sm font-semibold text-white placeholder-slate-500 focus:outline-none capitalize"
          />
          <button
            type="button"
            onClick={onToggleNotes}
            aria-label="Toggle notes"
            className={`p-1 rounded transition-colors ${
              exercise.showNotes || exercise.notes
                ? "text-brand-green bg-brand-green/10"
                : "text-slate-500 hover:text-slate-300 hover:bg-cardBorder"
            }`}
          >
            <MessageSquare size={12} />
          </button>
        </div>

        {priorLabel && (
          <div className="px-2 py-1 text-[10px] text-slate-500 border-b border-cardBorder bg-dashboard/30">
            {priorLabel}
          </div>
        )}

        {exercise.showNotes && (
          <div className="px-2 py-1.5 border-b border-cardBorder bg-dashboard/50">
            <textarea
              placeholder="Add notes..."
              value={exercise.notes}
              onChange={(e) => onNotesChange(e.target.value)}
              className="w-full bg-transparent text-[11px] text-slate-300 placeholder-slate-600 focus:outline-none resize-none"
              rows={1}
            />
          </div>
        )}

        {/* Sets table */}
        <div className="px-1.5 pt-1.5 pb-1">
          <div className="grid grid-cols-[20px_1fr_1fr_36px_28px] gap-2 mb-0.5 px-1 text-[9px] font-medium text-slate-500 uppercase tracking-wider">
            <div className="text-center">Set</div>
            <div className="text-center">kg</div>
            <div className="text-center">Reps</div>
            <div className="text-center">RPE</div>
            <div className="text-center">
              <Check size={10} className="mx-auto" />
            </div>
          </div>

          <div className="space-y-0.5">
            {exercise.sets.map((set, setIndex) => (
              <SetRow
                key={set.key}
                set={set}
                setNumber={setIndex + 1}
                onChangeField={(field, value) =>
                  onUpdateSetField(set.key, field, value)
                }
                onToggleComplete={() => onToggleComplete(set.key)}
              />
            ))}
          </div>

          <button
            type="button"
            onClick={onAddSet}
            className="w-full mt-1 py-1 flex items-center justify-center gap-1 text-[11px] font-medium text-slate-500 hover:text-white hover:bg-cardBorder/50 rounded transition-colors"
          >
            <Plus size={12} />
            Add Set
          </button>
        </div>
      </Card>

      {showLinkButton && (
        <div className="absolute left-1/2 -translate-x-1/2 -bottom-2.5 z-10">
          <button
            type="button"
            onClick={onToggleLinkNext}
            title={isLinkedToNext ? "Unlink superset" : "Create superset"}
            aria-label={isLinkedToNext ? "Unlink superset" : "Create superset"}
            className={`w-5 h-5 rounded-full flex items-center justify-center border border-cardBorder transition-colors shadow-sm ${
              isLinkedToNext
                ? "bg-brand-green text-dashboard border-brand-green"
                : "bg-card text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            {isLinkedToNext ? <Unlink size={10} /> : <LinkIcon size={10} />}
          </button>
        </div>
      )}
    </div>
  );
}

function SetRow({
  set,
  setNumber,
  onChangeField,
  onToggleComplete,
}: {
  set: SetDraft;
  setNumber: number;
  onChangeField: (field: SetField, value: string) => void;
  onToggleComplete: () => void;
}) {
  const completed = set.performed_at != null;
  return (
    <div
      className={`grid grid-cols-[20px_1fr_1fr_36px_28px] gap-2 items-center px-1 py-0.5 rounded transition-colors ${
        completed ? "bg-brand-green/10" : "bg-transparent hover:bg-cardBorder/10"
      }`}
    >
      <div className="text-center">
        <span className="text-[11px] font-medium text-slate-500">{setNumber}</span>
      </div>
      <input
        type="number"
        inputMode="decimal"
        placeholder="-"
        aria-label={`Set ${setNumber} weight`}
        value={set.weight}
        onChange={(e) => onChangeField("weight", e.target.value)}
        className={`w-full bg-transparent text-center text-sm font-bold focus:outline-none ${
          completed ? "text-brand-green" : "text-white"
        }`}
      />
      <input
        type="number"
        inputMode="numeric"
        placeholder="-"
        aria-label={`Set ${setNumber} reps`}
        value={set.reps}
        onChange={(e) => onChangeField("reps", e.target.value)}
        className={`w-full bg-transparent text-center text-sm font-bold focus:outline-none ${
          completed ? "text-brand-green" : "text-white"
        }`}
      />
      <input
        type="number"
        inputMode="decimal"
        placeholder="-"
        min={0}
        max={10}
        step={0.5}
        aria-label={`Set ${setNumber} RPE`}
        value={set.rpe}
        onChange={(e) => onChangeField("rpe", e.target.value)}
        className={`w-full bg-transparent text-center text-xs focus:outline-none ${
          completed ? "text-brand-green" : "text-slate-300"
        }`}
      />
      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={onToggleComplete}
          aria-label={
            completed ? `Unlog set ${setNumber}` : `Log set ${setNumber}`
          }
          aria-pressed={completed}
          className={`w-6 h-6 rounded flex items-center justify-center transition-colors ${
            completed
              ? "bg-brand-green text-dashboard"
              : "bg-cardBorder hover:bg-slate-600 text-slate-400"
          }`}
        >
          <Check size={12} strokeWidth={completed ? 3 : 2} />
        </button>
      </div>
    </div>
  );
}
