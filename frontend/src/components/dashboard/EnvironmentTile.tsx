import type {
  EnvironmentPollenPayload,
  EnvironmentTodayPayload,
} from "../../api/dashboard";
import {
  formatTemperature,
  formatWindSpeed,
  useUnits,
} from "../../hooks/useUnits";

interface Props {
  data: EnvironmentTodayPayload | null;
}

const POLLEN_THRESHOLD = 20;

const POLLEN_LABEL: Record<string, string> = {
  alder: "Alder",
  birch: "Birch",
  grass: "Grass",
  mugwort: "Mugwort",
  olive: "Olive",
  ragweed: "Ragweed",
};

export default function EnvironmentTile({ data }: Props) {
  const { units } = useUnits();

  if (!data || (!data.forecast && !data.air_quality)) {
    return (
      <div className="metric-card">
        <div className="label">Environment</div>
        <div className="value" style={{ color: "var(--text-muted)" }}>
          —
        </div>
        <div className="subtext">Set a default location in Settings</div>
      </div>
    );
  }

  const forecast = data.forecast;
  const aq = data.air_quality;
  const aqi = aq?.us_aqi ?? aq?.european_aqi ?? null;
  const pollens = topPollens(aq?.pollen ?? null);

  return (
    <div className="metric-card">
      <div
        className="label"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
      >
        <span>Environment</span>
        {aqi != null && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 8px",
              borderRadius: 999,
              background: aqiColor(aqi),
              color: "#fff",
              letterSpacing: 0.4,
            }}
          >
            AQI {aqi}
          </span>
        )}
      </div>
      <div className="value">
        {forecast?.temp_c != null ? formatTemperature(forecast.temp_c, units) : "—"}
      </div>
      <div className="subtext">
        {forecast?.conditions ?? ""}
        {forecast?.high_c != null && forecast?.low_c != null && (
          <span>
            {forecast.conditions ? " · " : ""}H {formatTemperature(forecast.high_c, units)} / L{" "}
            {formatTemperature(forecast.low_c, units)}
          </span>
        )}
        {forecast?.wind_ms != null && (
          <span> · wind {formatWindSpeed(forecast.wind_ms, units)}</span>
        )}
      </div>
      {pollens.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)" }}>
          Pollen:{" "}
          {pollens
            .map(([k, v]) => `${POLLEN_LABEL[k] ?? k} ${Math.round(v)}`)
            .join(" · ")}
        </div>
      )}
    </div>
  );
}

function topPollens(pollen: EnvironmentPollenPayload | null): [string, number][] {
  if (!pollen) return [];
  const entries = Object.entries(pollen).filter(
    (entry): entry is [string, number] =>
      typeof entry[1] === "number" && entry[1] >= POLLEN_THRESHOLD
  );
  entries.sort((a, b) => b[1] - a[1]);
  return entries.slice(0, 2);
}

function aqiColor(aqi: number): string {
  if (aqi <= 50) return "var(--green)";
  if (aqi <= 100) return "var(--orange)";
  return "var(--red)";
}
