import {
  Activity,
  Flame,
  Heart,
  MapPin,
  Mountain,
  RefreshCw,
  Timer,
  Zap,
} from "lucide-react";
import type { ActivityDetail } from "../../api/activities";
import type { WeatherSnapshot } from "../../api/weather";
import { useUnits } from "../../hooks/useUnits";
import AnalysisChart from "./AnalysisChart";
import MetricGrid, { type MetricCellData } from "./MetricGrid";
import SplitsTable from "./SplitsTable";
import WeatherStrip from "./WeatherStrip";
import ZonesBar from "./ZonesBar";
import {
  distanceToDisplay,
  elevationToDisplay,
  elevationUnitLabel,
  formatHmsCompact,
  speedShort,
  speedUnitLabel,
} from "./utils";

interface Props {
  activity: ActivityDetail;
  weather: WeatherSnapshot | null;
  streams: Record<string, number[]> | null;
  streamsLoading: boolean;
  streamsError: string | null;
  onLoadStreams: () => void;
}

export default function ActivityDetailRide({
  activity,
  weather,
  streams,
  streamsLoading,
  streamsError,
  onLoadStreams,
}: Props) {
  const { units } = useUnits();
  const cells: MetricCellData[] = [];

  if (activity.distance != null) {
    const distance = distanceToDisplay(activity.distance, units);
    cells.push({
      label: "Distance",
      icon: <MapPin size={12} />,
      value: distance.value,
      unit: distance.unit,
    });
  }
  cells.push({
    label: "Time",
    icon: <Timer size={12} />,
    value: formatHmsCompact(activity.moving_time),
  });
  if (activity.average_speed != null) {
    cells.push({
      label: "Avg Speed",
      icon: <Activity size={12} />,
      value: speedShort(activity.average_speed, units),
      unit: speedUnitLabel(units),
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
  if (activity.average_cadence != null) {
    cells.push({
      label: "Cadence",
      icon: <RefreshCw size={12} />,
      value: Math.round(activity.average_cadence).toString(),
      unit: "rpm",
    });
  }
  if (activity.average_power != null) {
    const avg = Math.round(activity.average_power);
    const np =
      activity.weighted_avg_power != null
        ? Math.round(activity.weighted_avg_power)
        : null;
    cells.push({
      label: "Power (Avg/NP)",
      icon: <Zap size={12} />,
      value: np != null ? `${avg} / ${np}` : `${avg}`,
      unit: "W",
    });
  }
  if (activity.total_elevation != null && activity.total_elevation > 0) {
    cells.push({
      label: "Elevation",
      icon: <Mountain size={12} />,
      value: elevationToDisplay(activity.total_elevation, units),
      unit: elevationUnitLabel(units),
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
        mode="ride"
        streams={streams}
        streamsLoading={streamsLoading}
        streamsError={streamsError}
        onLoadStreams={onLoadStreams}
        streamsCached={activity.streams_cached}
      />
      <ZonesBar zones={activity.zones} />
      <SplitsTable variant="ride" laps={activity.laps} />
    </div>
  );
}
