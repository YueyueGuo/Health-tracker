import { Card } from "../ui/Card";
import type { ZoneDistribution } from "../../api/activities";
import { HR_ZONE_COLORS, HR_ZONE_LABELS, formatHmsCompact } from "./utils";

interface Props {
  zones: ZoneDistribution[] | null;
}

export default function HRZonesBar({ zones }: Props) {
  const hr = zones?.find((z) => z.type === "heartrate");
  if (!hr || hr.distribution_buckets.length === 0) return null;

  const totalSeconds = hr.distribution_buckets.reduce(
    (acc, b) => acc + (b.time || 0),
    0
  );
  if (totalSeconds <= 0) return null;

  return (
    <Card className="!p-3">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-200">
          Time in HR Zones
        </h3>
      </div>
      <div className="space-y-2.5">
        {hr.distribution_buckets.map((b, i) => {
          const seconds = b.time || 0;
          const percent = Math.round((seconds / totalSeconds) * 100);
          const color = HR_ZONE_COLORS[i] ?? "#475569";
          const label = HR_ZONE_LABELS[i];
          return (
            <div key={i} className="flex items-center gap-2">
              <div
                className="w-6 text-[10px] font-bold text-slate-400"
                title={label}
              >
                Z{i + 1}
              </div>
              <div className="flex-1 h-3 bg-dashboard rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${percent}%`, backgroundColor: color }}
                />
              </div>
              <div className="w-12 text-right text-[10px] font-medium text-slate-300">
                {formatHmsCompact(seconds)}
              </div>
              <div className="w-8 text-right text-[9px] text-slate-500">
                {percent}%
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
