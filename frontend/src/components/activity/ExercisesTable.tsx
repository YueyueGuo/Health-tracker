import { Card } from "../ui/Card";
import type { ExerciseBreakdown } from "../../api/strength";
import { useUnits } from "../../hooks/useUnits";
import { formatVolumeWeight } from "./utils";

interface Props {
  exercises: ExerciseBreakdown[];
}

export default function ExercisesTable({ exercises }: Props) {
  const { units } = useUnits();
  if (!exercises || exercises.length === 0) return null;

  const gridClass = "grid grid-cols-[2fr_1fr_1fr_1.5fr] gap-1";

  return (
    <Card className="!p-3">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-200">Exercises</h3>
      </div>
      <div>
        <div
          className={`${gridClass} px-1 pb-1.5 text-[9px] font-medium text-slate-500 uppercase tracking-wider border-b border-cardBorder/50`}
        >
          <div>Exercise</div>
          <div>Sets</div>
          <div>Volume</div>
          <div className="text-right">HR (Avg/Max)</div>
        </div>
        <div className="space-y-0.5 mt-1">
          {exercises.map((ex) => {
            const hrAvgs = ex.sets
              .map((s) => s.avg_hr)
              .filter((v): v is number => typeof v === "number");
            const hrMaxes = ex.sets
              .map((s) => s.max_hr)
              .filter((v): v is number => typeof v === "number");
            const avg =
              hrAvgs.length > 0
                ? Math.round(hrAvgs.reduce((a, b) => a + b, 0) / hrAvgs.length)
                : null;
            const max =
              hrMaxes.length > 0 ? Math.round(Math.max(...hrMaxes)) : null;
            const hrCell =
              avg != null || max != null
                ? `${avg ?? "—"}/${max ?? "—"}`
                : "—";
            const vol = formatVolumeWeight(ex.total_volume, units);
            return (
              <div
                key={ex.name}
                className={`${gridClass} px-1 py-1.5 text-xs items-center rounded hover:bg-cardBorder/20 transition-colors`}
              >
                <div className="font-bold text-white truncate pr-2">
                  {ex.name}
                </div>
                <div className="font-medium text-slate-300">
                  {ex.sets.length}
                </div>
                <div className="font-medium text-white">
                  {vol.value}
                  {vol.unit && (
                    <span className="text-[10px] font-normal text-slate-500 ml-1">
                      {vol.unit}
                    </span>
                  )}
                </div>
                <div className="text-right font-medium text-white">
                  {hrCell}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}
