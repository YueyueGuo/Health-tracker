import { Dumbbell, Layers, ListChecks, Timer } from "lucide-react";
import { Link } from "react-router-dom";
import { Card } from "../ui/Card";
import { formatHmsCompact, formatVolumeWeight } from "../activity/utils";
import { useUnits } from "../../hooks/useUnits";
import type { StrengthSessionDetail } from "../../api/strength";

interface Props {
  session: StrengthSessionDetail;
}

function formatSessionDate(dateStr: string): string {
  // dateStr is YYYY-MM-DD; parse as a local date (avoid UTC drift to the
  // previous calendar day in negative-offset timezones).
  const [y, m, d] = dateStr.split("-").map(Number);
  if (!y || !m || !d) return dateStr;
  const local = new Date(y, m - 1, d);
  return local.toLocaleDateString("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function deriveDurationSec(session: StrengthSessionDetail): number | null {
  if (session.duration_sec != null) return session.duration_sec;
  // Fallback: derive from started_at/ended_at if both stamped, otherwise
  // from the performed_at range across the session's sets.
  if (session.started_at && session.ended_at) {
    const start = new Date(session.started_at).getTime();
    const end = new Date(session.ended_at).getTime();
    if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
      return Math.round((end - start) / 1000);
    }
  }
  const stamps = session.sets
    .map((s) => (s.performed_at ? new Date(s.performed_at).getTime() : null))
    .filter((t): t is number => t != null && Number.isFinite(t));
  if (stamps.length < 2) return null;
  return Math.round((Math.max(...stamps) - Math.min(...stamps)) / 1000);
}

function deriveTotalVolumeKg(session: StrengthSessionDetail): number {
  if (session.total_volume_kg != null) return session.total_volume_kg;
  return session.exercises.reduce(
    (acc, ex) => acc + (ex.total_volume ?? 0),
    0,
  );
}

function deriveTotalSets(session: StrengthSessionDetail): number {
  if (session.total_sets != null) return session.total_sets;
  return session.sets.length;
}

function deriveExerciseCount(session: StrengthSessionDetail): number {
  if (session.exercise_count != null) return session.exercise_count;
  return session.exercises.length;
}

export function SessionSummaryCard({ session }: Props) {
  const { units } = useUnits();
  const durationSec = deriveDurationSec(session);
  const totalVolumeKg = deriveTotalVolumeKg(session);
  const totalSets = deriveTotalSets(session);
  const exerciseCount = deriveExerciseCount(session);
  const volume = formatVolumeWeight(totalVolumeKg, units);
  const dateLabel = formatSessionDate(session.date);

  return (
    <Card className="!p-4 mb-3">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h1 className="text-base font-bold text-white tracking-tight">
            Strength Session
          </h1>
          <p className="text-[11px] text-slate-400">{dateLabel}</p>
        </div>
        {session.activity_id != null && (
          <Link
            to={`/activities/${session.activity_id}`}
            className="text-[10px] font-medium px-2 py-1 rounded-md border border-cardBorder text-slate-300 hover:text-white hover:border-slate-500 transition-colors"
          >
            View Strava →
          </Link>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <SummaryTile
          icon={<Timer size={12} />}
          label="Duration"
          value={formatHmsCompact(durationSec)}
        />
        <SummaryTile
          icon={<Dumbbell size={12} />}
          label="Volume"
          value={volume.value}
          unit={volume.unit}
        />
        <SummaryTile
          icon={<Layers size={12} />}
          label="Exercises"
          value={exerciseCount.toString()}
        />
        <SummaryTile
          icon={<ListChecks size={12} />}
          label="Sets"
          value={totalSets.toString()}
        />
      </div>
    </Card>
  );
}

function SummaryTile({
  icon,
  label,
  value,
  unit,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-1 text-slate-400 mb-0.5">
        {icon}
        <span className="text-[9px] uppercase tracking-wider font-medium">
          {label}
        </span>
      </div>
      <div className="text-sm font-bold text-white">
        {value}
        {unit && (
          <span className="text-[10px] font-normal text-slate-400 ml-1">
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

export default SessionSummaryCard;
