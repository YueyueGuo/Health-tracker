import { Card } from "../ui/Card";
import type { ExerciseBreakdown } from "../../api/strength";
import { useUnits, type UnitSystem } from "../../hooks/useUnits";

interface Props {
  exercise: ExerciseBreakdown;
}

function formatWeight(kg: number | null, units: UnitSystem): string {
  if (kg == null) return "—";
  if (units === "imperial") return Math.round(kg * 2.20462).toString();
  return Math.round(kg).toString();
}

function formatEst1rm(kg: number | null, units: UnitSystem): string | null {
  if (kg == null) return null;
  if (units === "imperial") {
    return `${Math.round(kg * 2.20462)} lb`;
  }
  return `${Math.round(kg)} kg`;
}

export function ExerciseDetailCard({ exercise }: Props) {
  const { units } = useUnits();
  const weightHeader = units === "imperial" ? "lb" : "kg";
  const est1rm = formatEst1rm(exercise.est_1rm, units);
  const hasHr = exercise.sets.some(
    (s) => s.avg_hr != null || s.max_hr != null,
  );

  // Grid columns: Set | Weight | Reps | RPE | (HR avg/max)
  const gridClass = hasHr
    ? "grid grid-cols-[24px_1fr_1fr_44px_1.2fr] gap-2"
    : "grid grid-cols-[24px_1fr_1fr_44px] gap-2";

  return (
    <Card className="!p-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white truncate">
          {exercise.name}
        </h3>
        {est1rm != null && (
          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-brand-green/10 text-brand-green">
            1RM {est1rm}
          </span>
        )}
      </div>

      <div
        className={`${gridClass} px-1 pb-1 text-[9px] font-medium text-slate-500 uppercase tracking-wider border-b border-cardBorder/50`}
      >
        <div className="text-center">Set</div>
        <div className="text-center">{weightHeader}</div>
        <div className="text-center">Reps</div>
        <div className="text-center">RPE</div>
        {hasHr && <div className="text-right">HR (Avg/Max)</div>}
      </div>

      <div className="mt-1 space-y-0.5">
        {exercise.sets.map((set) => (
          <div
            key={set.id}
            className={`${gridClass} items-center px-1 py-1 rounded text-xs hover:bg-cardBorder/20 transition-colors`}
          >
            <div className="text-center font-medium text-slate-500">
              {set.set_number}
            </div>
            <div className="text-center font-bold text-white">
              {formatWeight(set.weight_kg, units)}
            </div>
            <div className="text-center font-bold text-white">{set.reps}</div>
            <div className="text-center text-slate-300">
              {set.rpe != null ? set.rpe : "—"}
            </div>
            {hasHr && (
              <div className="text-right font-medium text-white">
                {set.avg_hr != null || set.max_hr != null
                  ? `${set.avg_hr ?? "—"}/${set.max_hr ?? "—"}`
                  : "—"}
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

export default ExerciseDetailCard;
