import { Bike, Dumbbell, Flame, Mountain, Heart } from "lucide-react";
import { Card } from "../ui/Card";
import { useApi } from "../../hooks/useApi";
import { fetchLatestWorkoutInsight } from "../../api/insights";
import { fetchStrengthSessionOptional } from "../../api/strength";
import type { LatestWorkoutSnapshot } from "../../api/insights";
import type { StrengthSessionDetail } from "../../api/strength";
import {
  formatDistanceShort,
  formatElevation,
  useUnits,
} from "../../hooks/useUnits";

export function YesterdayActivityCard() {
  const { units } = useUnits();
  const insight = useApi(() => fetchLatestWorkoutInsight());

  const workout = insight.data?.workout ?? null;
  const workoutDate = workoutDateOnly(workout);

  const strength = useApi(
    () =>
      workoutDate
        ? fetchStrengthSessionOptional(workoutDate)
        : Promise.resolve(null),
    [workoutDate]
  );

  if (insight.loading) {
    return (
      <Card className="p-4">
        <div className="text-xs text-slate-500">Loading recent activity…</div>
      </Card>
    );
  }

  if (insight.error || !workout) {
    return (
      <Card className="p-4">
        <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-3">
          Recent Activity
        </h3>
        <p className="text-xs text-slate-500">
          {insight.error
            ? "Couldn't load latest workout."
            : "No recent workouts. Sync to see activity."}
        </p>
      </Card>
    );
  }

  const heading = relativeDateHeading(workoutDate);
  const sport = workout.sport_type?.toLowerCase() ?? "";
  const isRide = sport.includes("ride");
  const SportIcon = isRide ? Bike : Heart;

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wider">
          {heading}
        </h3>
        <span className="text-[10px] font-medium text-slate-500 bg-slate-800/50 px-2 py-0.5 rounded">
          {strength.data ? "Strava + Strength" : "Strava"}
        </span>
      </div>

      <div
        className={`${
          strength.data ? "mb-4 pb-4 border-b border-cardBorder" : ""
        }`}
      >
        <div className="flex items-center gap-2 mb-3">
          <SportIcon
            size={16}
            className={isRide ? "text-orange-500" : "text-brand-green"}
          />
          <span className="font-medium text-slate-200 text-sm">
            {workout.name}
          </span>
          {workout.classification_type && (
            <span className="text-[10px] px-1.5 py-0.5 bg-brand-green/10 text-brand-green rounded ml-auto capitalize">
              {workout.classification_type}
            </span>
          )}
        </div>

        <div className="grid grid-cols-4 gap-2 mb-3">
          <Metric
            label="Distance"
            value={
              workout.distance_m != null
                ? formatDistanceShort(workout.distance_m, units)
                : null
            }
          />
          <Metric label="Time" value={formatDuration(workout.moving_time_s)} />
          <Metric
            label={isRide ? "TSS" : "RE"}
            value={
              workout.suffer_score != null
                ? Math.round(workout.suffer_score).toString()
                : null
            }
            valueClass="text-brand-amber"
          />
          <Metric
            label={isRide ? "NP" : "Pace"}
            value={
              isRide
                ? workout.weighted_avg_power_w != null
                  ? `${Math.round(workout.weighted_avg_power_w)}`
                  : null
                : workout.pace
            }
            unit={isRide && workout.weighted_avg_power_w != null ? "W" : undefined}
          />
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
          {workout.avg_hr != null && (
            <div className="flex items-center gap-1">
              <Heart size={12} />{" "}
              {Math.round(workout.avg_hr)}
              {workout.max_hr != null
                ? ` avg / ${Math.round(workout.max_hr)} max`
                : " avg"}
            </div>
          )}
          {workout.total_elevation_m != null && workout.total_elevation_m > 0 && (
            <div className="flex items-center gap-1">
              <Mountain size={12} />{" "}
              {formatElevation(workout.total_elevation_m, units)}
            </div>
          )}
          {workout.calories != null && (
            <div className="flex items-center gap-1">
              <Flame size={12} /> {Math.round(workout.calories)} kcal
            </div>
          )}
        </div>
      </div>

      {strength.data && (
        <StrengthSection session={strength.data} units={units} />
      )}
    </Card>
  );
}

function StrengthSection({
  session,
  units,
}: {
  session: StrengthSessionDetail;
  units: ReturnType<typeof useUnits>["units"];
}) {
  const totalVolumeKg = session.exercises.reduce(
    (sum, ex) => sum + (ex.total_volume ?? 0),
    0
  );
  const volumeDisplay =
    units === "imperial"
      ? `${Math.round(totalVolumeKg * 2.20462).toLocaleString()} lb`
      : `${Math.round(totalVolumeKg).toLocaleString()} kg`;

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Dumbbell size={16} className="text-slate-300" />
        <span className="font-medium text-slate-200 text-sm">
          Strength Session
        </span>
        <div className="ml-auto text-right">
          <span className="text-sm font-bold text-white">
            {volumeDisplay}
            <span className="text-[10px] text-slate-400 font-normal ml-0.5">
              vol
            </span>
          </span>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-[11px]">
        {session.exercises.slice(0, 4).map((ex) => (
          <span
            key={ex.name}
            className="px-2 py-1 rounded bg-cardBorder/30 text-slate-300"
          >
            <span className="text-slate-500 mr-1">{ex.name}</span>
            {summarizeSets(ex.sets, units)}
          </span>
        ))}
      </div>
    </div>
  );
}

function summarizeSets(
  sets: { reps: number; weight_kg: number | null }[],
  units: ReturnType<typeof useUnits>["units"]
): string {
  if (sets.length === 0) return "—";
  const reps = sets[0].reps;
  const weight = sets[0].weight_kg;
  const allSameReps = sets.every((s) => s.reps === reps);
  const allSameWeight = sets.every((s) => s.weight_kg === weight);
  if (allSameReps && allSameWeight && weight != null) {
    const w =
      units === "imperial" ? Math.round(weight * 2.20462) : Math.round(weight);
    return `${sets.length}×${reps}@${w}`;
  }
  return `${sets.length} sets`;
}

function Metric({
  label,
  value,
  unit,
  valueClass = "text-white",
}: {
  label: string;
  value: string | null;
  unit?: string;
  valueClass?: string;
}) {
  return (
    <div>
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className={`text-sm font-bold ${valueClass}`}>
        {value ?? "—"}
        {value != null && unit && (
          <span className="text-[10px] text-slate-400 font-normal ml-0.5">
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

function formatDuration(seconds: number | null): string | null {
  if (seconds == null) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

function workoutDateOnly(workout: LatestWorkoutSnapshot | null): string | null {
  const iso = workout?.start_date_local ?? workout?.start_date ?? null;
  if (!iso) return null;
  return iso.slice(0, 10);
}

function relativeDateHeading(date: string | null): string {
  if (!date) return "Latest Activity";
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const yStr = `${yesterday.getFullYear()}-${pad(yesterday.getMonth() + 1)}-${pad(yesterday.getDate())}`;
  if (date === todayStr) return "Today's Activity";
  if (date === yStr) return "Yesterday's Activity";
  return "Latest Activity";
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}
