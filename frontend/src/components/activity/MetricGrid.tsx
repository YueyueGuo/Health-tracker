import type { ReactNode } from "react";
import { Card } from "../ui/Card";

export interface MetricCellData {
  label: string;
  icon: ReactNode;
  value: string;
  unit?: string;
  /** Override value color (e.g. brand-amber for Effort/TSS). */
  valueClass?: string;
}

interface Props {
  cells: MetricCellData[];
  /** Override the grid template (default 3 even columns). The mockup uses
   *  a 3-col grid; some sport layouts (Strength) use 2 cols on small width. */
  gridClass?: string;
}

export default function MetricGrid({
  cells,
  gridClass = "grid-cols-3",
}: Props) {
  return (
    <Card className="!p-3">
      <div className={`grid ${gridClass} gap-y-4 gap-x-2`}>
        {cells.map((c) => (
          <div key={c.label}>
            <div className="flex items-center gap-1 text-slate-400 mb-0.5">
              {c.icon}
              <span className="text-[9px] uppercase tracking-wider font-medium">
                {c.label}
              </span>
            </div>
            <div
              className={`text-xs font-bold ${c.valueClass ?? "text-white"}`}
            >
              {c.value}
              {c.unit && (
                <span className="text-[10px] font-normal text-slate-500 ml-1">
                  {c.unit}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
