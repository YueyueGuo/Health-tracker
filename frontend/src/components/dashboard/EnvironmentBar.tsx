import { Thermometer, Wind, CloudRain, Mountain, Leaf } from "lucide-react";
import type {
  EnvironmentPollenPayload,
  EnvironmentTodayPayload,
} from "../../api/dashboard";
import {
  formatElevation,
  formatTemperature,
  formatWindSpeed,
  useUnits,
} from "../../hooks/useUnits";

interface Props {
  data: EnvironmentTodayPayload | null;
  baseElevationM?: number | null;
}

const POLLEN_LABELS: Record<string, string> = {
  alder: "Alder",
  birch: "Birch",
  grass: "Grass",
  mugwort: "Mugwort",
  olive: "Olive",
  ragweed: "Ragweed",
};

export function EnvironmentBar({ data, baseElevationM }: Props) {
  const { units } = useUnits();
  const forecast = data?.forecast ?? null;
  const aq = data?.air_quality ?? null;
  const aqi = aq?.us_aqi ?? aq?.european_aqi ?? null;

  const topPollen = topPollenEntry(aq?.pollen ?? null);

  return (
    <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 pb-4 text-xs text-slate-300">
      {forecast?.temp_c != null && (
        <div className="flex items-center gap-1.5">
          <Thermometer size={14} className="text-slate-400" />
          <span>{formatTemperature(forecast.temp_c, units)}</span>
        </div>
      )}

      {forecast?.wind_ms != null && (
        <div className="flex items-center gap-1.5">
          <Wind size={14} className="text-slate-400" />
          <span>{formatWindSpeed(forecast.wind_ms, units)}</span>
        </div>
      )}

      {aqi != null && (
        <div className="flex items-center gap-1.5">
          <CloudRain size={14} className={aqiColor(aqi)} />
          <span>AQI {aqi}</span>
        </div>
      )}

      {topPollen && (
        <div className="flex items-center gap-1.5">
          <Leaf size={14} className="text-brand-amber" />
          <span>
            {POLLEN_LABELS[topPollen.key] ?? topPollen.key}{" "}
            {pollenLevel(topPollen.value)}
          </span>
        </div>
      )}

      {baseElevationM != null && (
        <div className="flex items-center gap-1.5">
          <Mountain size={14} className="text-slate-400" />
          <span>{formatElevation(baseElevationM, units)}</span>
        </div>
      )}
    </div>
  );
}

function aqiColor(aqi: number): string {
  if (aqi <= 50) return "text-brand-green";
  if (aqi <= 100) return "text-brand-amber";
  return "text-brand-red";
}

function pollenLevel(value: number): string {
  if (value < 20) return "Low";
  if (value < 80) return "Mod";
  return "High";
}

function topPollenEntry(
  pollen: EnvironmentPollenPayload | null
): { key: string; value: number } | null {
  if (!pollen) return null;
  let top: { key: string; value: number } | null = null;
  for (const [k, v] of Object.entries(pollen) as [string, number | null][]) {
    if (typeof v === "number" && v >= 20 && (!top || v > top.value)) {
      top = { key: k, value: v };
    }
  }
  return top;
}
