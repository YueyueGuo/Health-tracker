import { Card } from "../ui/Card";
import type { ZoneBucket, ZoneDistribution } from "../../api/activities";
import { HR_ZONE_COLORS, HR_ZONE_LABELS, formatHmsCompact } from "./utils";

interface Props {
  zones: ZoneDistribution[] | null;
}

const GENERIC_ZONE_COLORS = ["#64748b", "#38bdf8", "#60a5fa", "#818cf8", "#a78bfa"];

export default function ZonesBar({ zones }: Props) {
  const renderableZones = (zones ?? [])
    .map((zone) => ({
      zone,
      totalSeconds: zone.distribution_buckets.reduce(
        (acc, bucket) => acc + (bucket.time || 0),
        0
      ),
    }))
    .filter(({ zone, totalSeconds }) => zone.distribution_buckets.length > 0 && totalSeconds > 0);

  if (renderableZones.length === 0) return null;

  return (
    <div className="space-y-3">
      {renderableZones.map(({ zone, totalSeconds }) => (
        <Card key={zone.type} className="!p-3">
          <div className="mb-3">
            <h3 className="text-sm font-semibold text-slate-200">
              Time in {zoneTitle(zone.type)} Zones
            </h3>
          </div>
          <div className="space-y-2.5">
            {zone.distribution_buckets.map((bucket, i) => {
              const seconds = bucket.time || 0;
              const percent = Math.round((seconds / totalSeconds) * 100);
              const color = zoneColor(zone.type, i);
              const label = zoneLabel(zone.type, bucket, i);
              return (
                <div key={i} className="flex items-center gap-2">
                  <div
                    className="w-12 text-[10px] font-bold text-slate-400 truncate"
                    title={label.title}
                  >
                    {label.short}
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
      ))}
    </div>
  );
}

function zoneTitle(type: string): string {
  if (type === "heartrate") return "HR";
  return type.charAt(0).toUpperCase() + type.slice(1);
}

function zoneColor(type: string, index: number): string {
  if (type === "heartrate") return HR_ZONE_COLORS[index] ?? "#475569";
  return GENERIC_ZONE_COLORS[index] ?? "#475569";
}

function zoneLabel(
  type: string,
  bucket: ZoneBucket,
  index: number
): { short: string; title: string } {
  const zone = `Z${index + 1}`;
  if (type === "heartrate") {
    const label = HR_ZONE_LABELS[index] ?? zone;
    return { short: zone, title: label };
  }

  const range = zoneRange(type, bucket);
  return {
    short: zone,
    title: range ? `${zone} (${range})` : zone,
  };
}

function zoneRange(type: string, bucket: ZoneBucket): string | null {
  const unit = type === "power" ? " W" : "";
  if (bucket.max === -1) return `>=${bucket.min}${unit}`;
  if (bucket.min === 0 && bucket.max === 0) return null;
  return `${bucket.min}-${bucket.max}${unit}`;
}
