import {
  Activity,
  Bike,
  ChevronRight,
  Dumbbell,
  Footprints,
  Heart,
  Moon,
  Mountain,
} from "lucide-react";
import { Card } from "../ui/Card";
import {
  formatRelativeDate,
  type EventType,
  type HistoryEvent,
} from "../../lib/historyEvents";

interface Props {
  event: HistoryEvent;
  onClick?: () => void;
}

function TypeIcon({ type }: { type: EventType }) {
  switch (type) {
    case "Ride":
      return <Bike size={16} className="text-orange-500" />;
    case "Run":
      return <Activity size={16} className="text-brand-green" />;
    case "Strength":
      return <Dumbbell size={16} className="text-slate-300" />;
    case "Hike":
      return <Mountain size={16} className="text-emerald-600" />;
    case "Walk":
      return <Footprints size={16} className="text-slate-400" />;
    case "MorningStatus":
      return (
        <div className="flex items-center gap-0.5">
          <Heart size={14} className="text-brand-green" />
          <Moon size={14} className="text-sky-400" />
        </div>
      );
    case "Other":
    default:
      return <Activity size={16} className="text-slate-400" />;
  }
}

export function HistoryEventCard({ event, onClick }: Props) {
  const interactive = onClick != null;
  const wrapperClass = [
    "!p-3 group",
    interactive ? "cursor-pointer hover:bg-cardBorder/20 active:scale-[0.98] transition-all" : "",
    event.highlight ? "border-brand-amber/30 bg-brand-amber/5" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const iconBg =
    event.type === "MorningStatus"
      ? "bg-slate-800/30 border-cardBorder"
      : "bg-dashboard border-cardBorder";

  const content = (
    <>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2.5">
          <div className={`p-2 rounded-lg border ${iconBg}`}>
            <TypeIcon type={event.type} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-200">
              {event.title}
            </h3>
            <p className="text-[11px] text-slate-500">
              {formatRelativeDate(event.timestamp)}
            </p>
          </div>
        </div>
        {interactive && (
          <ChevronRight
            size={16}
            className="text-slate-600 group-hover:text-slate-400 transition-colors mt-1"
          />
        )}
      </div>

      <div className="flex items-start gap-4 pl-11">
        {event.metrics.map((metric, idx) => (
          <div key={idx}>
            <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-0.5">
              {metric.label}
            </div>
            <div
              className={`text-xs font-semibold ${
                metric.colorClass || "text-white"
              }`}
            >
              {metric.value}
            </div>
          </div>
        ))}
      </div>
    </>
  );

  return (
    <Card className={wrapperClass}>
      {interactive ? (
        <button
          type="button"
          onClick={onClick}
          className="w-full text-left"
          aria-label={`Open ${event.title}`}
        >
          {content}
        </button>
      ) : (
        content
      )}
    </Card>
  );
}
