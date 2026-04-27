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
import HRZonesBar from "./HRZonesBar";
import MetricGrid, { type MetricCellData } from "./MetricGrid";
import SplitsTable from "./SplitsTable";
import WeatherStrip from "./WeatherStrip";
import {
  distanceUnitLabel,
  elevationToDisplay,
  elevationUnitLabel,
  formatHmsCompact,
  metersToDisplay,
  paceShort,
  paceUnitLabel,
} from "./utils";

interface Props {
  activity: ActivityDetail;
  weather: WeatherSnapshot | null;
  streams: Record<string, number[]> | null;
  streamsLoading: boolean;
  streamsError: string | null;
  onLoadStreams: () => void;
}

export default function ActivityDetailRun({
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
    cells.push({
      label: "Distance",
      icon: <MapPin size={12} />,
      value: metersToDisplay(activity.distance, units),
      unit: distanceUnitLabel(units),
    });
  }
  cells.push({
    label: "Time",
    icon: <Timer size={12} />,
    value: formatHmsCompact(activity.moving_time),
  });
  if (activity.average_speed != null) {
    cells.push({
      label: "Avg Pace",
      icon: <Activity size={12} />,
      value: paceShort(activity.average_speed, units),
      unit: paceUnitLabel(units),
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
      value: Math.round(activity.average_cadence * 2).toString(),
      unit: "spm",
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
        mode="run"
        streams={streams}
        streamsLoading={streamsLoading}
        streamsError={streamsError}
        onLoadStreams={onLoadStreams}
        streamsCached={activity.streams_cached}
      />
      <HRZonesBar zones={activity.zones} />
      <SplitsTable variant="run" laps={activity.laps} />
    </div>
  );
}
