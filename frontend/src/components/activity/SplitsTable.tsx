import { Card } from "../ui/Card";
import type { ActivityLap } from "../../api/activities";
import { useUnits } from "../../hooks/useUnits";
import {
  elevationToDisplay,
  metersToDisplay,
  paceShort,
  speedShort,
} from "./utils";

interface Props {
  variant: "run" | "ride";
  laps: ActivityLap[];
}

export default function SplitsTable({ variant, laps }: Props) {
  const { units } = useUnits();
  if (!laps || laps.length === 0) return null;

  const headerCols =
    variant === "run"
      ? ["Lap", "Dist", "Pace", "HR (Avg/Max)", "Elev"]
      : ["Lap", "Dist", "Speed", "HR (Avg/Max)", "Power"];

  const gridClass = "grid grid-cols-[24px_1fr_1fr_1.5fr_1fr] gap-1";

  return (
    <Card className="!p-3">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-200">Splits</h3>
      </div>
      <div>
        <div
          className={`${gridClass} px-1 pb-1.5 text-[9px] font-medium text-slate-500 uppercase tracking-wider border-b border-cardBorder/50`}
        >
          {headerCols.map((c, i) => (
            <div key={c} className={i === headerCols.length - 1 ? "text-right" : ""}>
              {c}
            </div>
          ))}
        </div>
        <div className="space-y-0.5 mt-1">
          {laps.map((lap) => {
            const hrCell =
              lap.average_heartrate || lap.max_heartrate
                ? `${lap.average_heartrate ? Math.round(lap.average_heartrate) : "—"}/${lap.max_heartrate ? Math.round(lap.max_heartrate) : "—"}`
                : "—";
            return (
              <div
                key={lap.lap_index}
                className={`${gridClass} px-1 py-1.5 text-xs items-center rounded hover:bg-cardBorder/20 transition-colors`}
              >
                <div className="font-bold text-slate-400">{lap.lap_index}</div>
                <div className="font-medium text-white">
                  {metersToDisplay(lap.distance, units)}
                </div>
                {variant === "run" ? (
                  <div className="font-medium text-white">
                    {paceShort(lap.average_speed, units)}
                  </div>
                ) : (
                  <div className="font-medium text-white">
                    {speedShort(lap.average_speed, units)}
                  </div>
                )}
                <div className="font-medium text-white">{hrCell}</div>
                {variant === "run" ? (
                  <div className="text-right text-slate-400">
                    {lap.total_elevation_gain != null
                      ? elevationToDisplay(lap.total_elevation_gain, units)
                      : "—"}
                  </div>
                ) : (
                  <div className="text-right font-medium text-brand-amber">
                    {lap.average_watts != null
                      ? `${Math.round(lap.average_watts)}W`
                      : "—"}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}
