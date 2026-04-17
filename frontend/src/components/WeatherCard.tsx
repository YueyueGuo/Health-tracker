import type { WeatherSnapshot } from "../api/weather";
import {
  formatTemperature,
  formatWindSpeed,
  useUnits,
} from "../hooks/useUnits";

interface Props {
  weather: WeatherSnapshot | null;
}

/**
 * Compact weather card for ActivityDetail. Renders nothing when no
 * snapshot is available — the parent decides layout / placement.
 */
export default function WeatherCard({ weather }: Props) {
  const { units } = useUnits();
  if (!weather) return null;

  const iconCode = extractIconCode(weather);
  const iconUrl = iconCode
    ? `https://openweathermap.org/img/wn/${iconCode}@2x.png`
    : null;

  return (
    <div className="card weather-card">
      <div className="weather-header">
        <h2>Weather</h2>
        {weather.description && (
          <span className="weather-sub">{titleCase(weather.description)}</span>
        )}
      </div>
      <div className="weather-body">
        {iconUrl && (
          <img
            src={iconUrl}
            alt={weather.description || weather.conditions || "weather icon"}
            className="weather-icon"
            width={72}
            height={72}
          />
        )}
        <div className="weather-temp-block">
          {weather.temp_c != null && (
            <div className="weather-temp">
              {formatTemperature(weather.temp_c, units)}
            </div>
          )}
          {weather.feels_like_c != null && weather.temp_c != null && (
            <div className="weather-feels">
              Feels like {formatTemperature(weather.feels_like_c, units)}
            </div>
          )}
          {weather.conditions && (
            <div className="weather-conditions">{weather.conditions}</div>
          )}
        </div>
        <div className="weather-metrics">
          {weather.humidity != null && (
            <WeatherMetric label="Humidity" value={`${Math.round(weather.humidity)}%`} />
          )}
          {weather.wind_speed != null && (
            <WeatherMetric
              label="Wind"
              value={formatWind(weather.wind_speed, weather.wind_deg, units)}
            />
          )}
          {weather.wind_gust != null && (
            <WeatherMetric
              label="Gust"
              value={formatWindSpeed(weather.wind_gust, units)}
            />
          )}
          {weather.uv_index != null && (
            <WeatherMetric
              label="UV"
              value={weather.uv_index.toFixed(1)}
            />
          )}
          {weather.pressure != null && (
            <WeatherMetric
              label="Pressure"
              value={`${Math.round(weather.pressure)} hPa`}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────

function WeatherMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="weather-metric">
      <div className="weather-metric-label">{label}</div>
      <div className="weather-metric-value">{value}</div>
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────

function formatWind(
  speedMps: number,
  deg: number | null,
  units: "imperial" | "metric"
): string {
  const base = formatWindSpeed(speedMps, units);
  if (deg == null) return base;
  return `${base} ${windArrow(deg)}`;
}

/**
 * Unicode arrow pointing in the direction the wind is blowing *toward*.
 * OpenWeatherMap's ``wind_deg`` is the direction wind comes *from* (met
 * convention), so we add 180° to flip it to a "moving toward" arrow.
 */
function windArrow(deg: number): string {
  const adjusted = (deg + 180) % 360;
  const arrows = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"];
  const idx = Math.round(adjusted / 45) % 8;
  return arrows[idx];
}

function titleCase(s: string): string {
  return s
    .split(" ")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

/**
 * Extract the OpenWeatherMap icon code from the raw payload when
 * available. Returns ``null`` if ``raw_data`` wasn't included or the
 * shape doesn't match.
 */
function extractIconCode(weather: WeatherSnapshot): string | null {
  const raw = weather.raw_data;
  if (!raw) return null;
  try {
    const data = Array.isArray(raw.data) ? raw.data[0] : raw;
    const w = data?.weather;
    if (Array.isArray(w) && w.length > 0 && typeof w[0]?.icon === "string") {
      return w[0].icon;
    }
  } catch {
    /* ignore */
  }
  return null;
}
