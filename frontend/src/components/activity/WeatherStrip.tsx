import { useState } from "react";
import { Cloud, Droplets, Thermometer, Wind, ChevronDown } from "lucide-react";
import type { WeatherSnapshot } from "../../api/weather";
import {
  formatTemperature,
  formatWindSpeed,
  useUnits,
} from "../../hooks/useUnits";
import WeatherCard from "../WeatherCard";

interface Props {
  weather: WeatherSnapshot | null;
}

export default function WeatherStrip({ weather }: Props) {
  const { units } = useUnits();
  const [expanded, setExpanded] = useState(false);

  if (!weather) return null;

  const temp =
    weather.temp_c != null ? formatTemperature(weather.temp_c, units) : null;
  const humidity =
    weather.humidity != null ? `${Math.round(weather.humidity)}%` : null;
  const conditions =
    weather.conditions || (weather.description ? weather.description : null);
  const wind =
    weather.wind_speed != null
      ? formatWindSpeed(weather.wind_speed, units)
      : null;

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        aria-label={expanded ? "Hide weather details" : "Show weather details"}
        className="w-full flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2 bg-cardBorder/20 rounded-xl border border-cardBorder/50 hover:bg-cardBorder/30 transition-colors text-left"
      >
        {temp && (
          <div className="flex items-center gap-1 text-xs text-slate-300">
            <Thermometer size={14} className="text-slate-400" /> {temp}
          </div>
        )}
        {humidity && (
          <div className="flex items-center gap-1 text-xs text-slate-300">
            <Droplets size={14} className="text-slate-400" /> {humidity}
          </div>
        )}
        {conditions && (
          <div className="flex items-center gap-1 text-xs text-slate-300">
            <Cloud size={14} className="text-slate-400" /> {conditions}
          </div>
        )}
        {wind && (
          <div className="flex items-center gap-1 text-xs text-slate-300">
            <Wind size={14} className="text-slate-400" /> {wind}
          </div>
        )}
        <ChevronDown
          size={14}
          className={`ml-auto text-slate-500 transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>
      {expanded && <WeatherCard weather={weather} />}
    </div>
  );
}
