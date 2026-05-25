import { Card } from "../ui/Card";
import type {
  ExerciseBreakdown,
  StrengthSessionLink,
  StrengthSessionSegmentation,
} from "../../api/strength";
import { useUnits } from "../../hooks/useUnits";

interface Props {
  exercises: ExerciseBreakdown[];
  link: StrengthSessionLink | null;
  segmentation: StrengthSessionSegmentation | null;
}

function formatWeight(
  kg: number | null,
  units: ReturnType<typeof useUnits>["units"]
): string {
  if (kg == null) return "—";
  if (units === "imperial") {
    return `${Math.round(kg * 2.20462).toLocaleString()} lb`;
  }
  return `${Math.round(kg).toLocaleString()} kg`;
}

export default function ExerciseSetsTable({
  exercises,
  link,
  segmentation,
}: Props) {
  const { units } = useUnits();
  if (!exercises || exercises.length === 0) return null;
  const showHr = link != null;
  const missingTooltip =
    segmentation != null
      ? `auto-segmentation found ${segmentation.detected_count} of ${segmentation.target_count} sets`
      : "no HR data available";

  const gridColsWithHr = "grid grid-cols-[40px_1fr_1fr_1fr_1fr] gap-2";
  const gridColsNoHr = "grid grid-cols-[40px_1fr_1fr] gap-2";
  const gridCols = showHr ? gridColsWithHr : gridColsNoHr;

  return (
    <Card className="!p-3" data-testid="exercise-sets-table">
      <h3 className="text-sm font-semibold text-slate-200 mb-3">
        Exercise breakdown
      </h3>
      <div className="space-y-4">
        {exercises.map((ex) => (
          <div key={ex.name}>
            <div className="flex items-baseline justify-between mb-1.5">
              <div className="text-sm font-semibold text-white truncate">
                {ex.name}
              </div>
              <div className="text-[10px] text-slate-500">
                {ex.sets.length} {ex.sets.length === 1 ? "set" : "sets"}
              </div>
            </div>
            <div
              className={`${gridCols} px-1 pb-1 text-[9px] font-medium text-slate-500 uppercase tracking-wider border-b border-cardBorder/50`}
            >
              <div>Set</div>
              <div>Reps</div>
              <div>Weight</div>
              {showHr && <div className="text-right">Avg HR</div>}
              {showHr && <div className="text-right">Max HR</div>}
            </div>
            <div className="space-y-0.5 mt-1">
              {ex.sets.map((set) => {
                const hasAvg = typeof set.avg_hr === "number";
                const hasMax = typeof set.max_hr === "number";
                return (
                  <div
                    key={set.id}
                    className={`${gridCols} px-1 py-1.5 text-xs items-center rounded`}
                  >
                    <div className="font-medium text-slate-400">
                      #{set.set_number}
                    </div>
                    <div className="font-medium text-slate-200">
                      {set.reps}
                    </div>
                    <div className="font-medium text-white">
                      {formatWeight(set.weight_kg, units)}
                    </div>
                    {showHr && (
                      <div className="text-right">
                        {hasAvg ? (
                          <span className="text-white">
                            {Math.round(set.avg_hr as number)}
                          </span>
                        ) : (
                          <span
                            className="text-slate-500"
                            title={missingTooltip}
                            data-testid={`set-${set.id}-avg-missing`}
                          >
                            —
                          </span>
                        )}
                      </div>
                    )}
                    {showHr && (
                      <div className="text-right">
                        {hasMax ? (
                          <span className="text-white">
                            {Math.round(set.max_hr as number)}
                          </span>
                        ) : (
                          <span
                            className="text-slate-500"
                            title={missingTooltip}
                            data-testid={`set-${set.id}-max-missing`}
                          >
                            —
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
