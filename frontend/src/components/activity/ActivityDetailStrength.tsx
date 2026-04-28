import { Dumbbell, Flame, Heart, Timer, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import type { ActivityDetail } from "../../api/activities";
import type { WeatherSnapshot } from "../../api/weather";
import {
  fetchStrengthSessionOptional,
  type StrengthSessionDetail,
} from "../../api/strength";
import { useUnits } from "../../hooks/useUnits";
import AnalysisChart from "./AnalysisChart";
import ExercisesTable from "./ExercisesTable";
import MetricGrid, { type MetricCellData } from "./MetricGrid";
import WeatherStrip from "./WeatherStrip";
import { formatHmsCompact, formatVolumeWeight } from "./utils";
import ZonesBar from "./ZonesBar";

interface Props {
  activity: ActivityDetail;
  weather: WeatherSnapshot | null;
  streams: Record<string, number[]> | null;
  streamsLoading: boolean;
  streamsError: string | null;
  onLoadStreams: () => void;
}

export default function ActivityDetailStrength({
  activity,
  weather,
  streams,
  streamsLoading,
  streamsError,
  onLoadStreams,
}: Props) {
  const { units } = useUnits();
  const [session, setSession] = useState<StrengthSessionDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    const date = activity.start_date_local?.slice(0, 10);
    if (!date) return;
    fetchStrengthSessionOptional(date)
      .then((s) => {
        if (!cancelled) setSession(s);
      })
      .catch(() => {
        if (!cancelled) setSession(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activity.start_date_local]);

  const totalVolumeKg =
    session?.exercises.reduce((acc, ex) => acc + ex.total_volume, 0) ?? null;
  const volume = formatVolumeWeight(totalVolumeKg, units);

  const cells: MetricCellData[] = [
    {
      label: "Time",
      icon: <Timer size={12} />,
      value: formatHmsCompact(activity.moving_time),
    },
  ];

  if (totalVolumeKg != null) {
    cells.push({
      label: "Volume",
      icon: <Dumbbell size={12} />,
      value: volume.value,
      unit: volume.unit,
    });
  }

  cells.push({
    label: "HR (Avg/Max)",
    icon: <Heart size={12} />,
    value:
      activity.average_hr != null || activity.max_hr != null
        ? `${activity.average_hr ? Math.round(activity.average_hr) : "—"} / ${activity.max_hr ? Math.round(activity.max_hr) : "—"}`
        : "—",
    unit: activity.average_hr != null || activity.max_hr != null ? "bpm" : undefined,
  });

  if (activity.calories != null) {
    cells.push({
      label: "Calories",
      icon: <Flame size={12} />,
      value: Math.round(activity.calories).toLocaleString(),
      unit: "kcal",
    });
  }

  if (activity.suffer_score != null) {
    cells.push({
      label: "Effort (TSS)",
      icon: <Zap size={12} />,
      value: Math.round(activity.suffer_score).toString(),
      valueClass: "text-brand-amber",
    });
  }

  return (
    <div className="space-y-3">
      <MetricGrid cells={cells} />
      <WeatherStrip weather={weather} />
      <AnalysisChart
        mode="strength"
        streams={streams}
        streamsLoading={streamsLoading}
        streamsError={streamsError}
        onLoadStreams={onLoadStreams}
        streamsCached={activity.streams_cached}
      />
      <ZonesBar zones={activity.zones} />
      {session && session.exercises.length > 0 && (
        <ExercisesTable exercises={session.exercises} />
      )}
    </div>
  );
}
