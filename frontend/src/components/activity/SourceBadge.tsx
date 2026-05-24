import { Apple } from "lucide-react";

export type SourceBadgeKind = "apple" | "strava";

interface Props {
  source: SourceBadgeKind | undefined;
  className?: string;
}

/** Small unobtrusive pill that surfaces the origin of a workout
 *  (Apple Health vs Strava). Renders nothing when `source` is undefined. */
export default function SourceBadge({ source, className = "" }: Props) {
  if (!source) return null;

  if (source === "strava") {
    return (
      <span
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-500/15 text-orange-400 border border-orange-500/30 ${className}`.trim()}
        aria-label="Source: Strava"
        data-testid="source-badge-strava"
      >
        Strava
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-500/15 text-slate-300 border border-slate-500/30 ${className}`.trim()}
      aria-label="Source: Apple Health"
      data-testid="source-badge-apple"
    >
      <Apple size={10} aria-hidden="true" />
      Apple
    </span>
  );
}
