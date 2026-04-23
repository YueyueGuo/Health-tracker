import { fetchJson, fetchOptionalJson } from "./http";

export interface WeatherSnapshot {
  id: number;
  activity_id: number;
  temp_c: number | null;
  feels_like_c: number | null;
  humidity: number | null;
  wind_speed: number | null;
  wind_gust: number | null;
  wind_deg: number | null;
  conditions: string | null;
  description: string | null;
  pressure: number | null;
  uv_index: number | null;
  created_at: string | null;
  /**
   * Full OpenWeatherMap payload. Only present when ``?raw=true`` was
   * passed; needed to render the weather icon (``data[0].weather[0].icon``).
   */
  raw_data?: Record<string, unknown> | null;
}

export interface WeatherBackfillResult {
  enriched: number;
  skipped: number;
  failed: number;
  remaining: number;
  batch: number;
  dry_run: boolean;
  configured: boolean;
}

/**
 * Fetch the weather snapshot joined to ``activityId``.
 *
 * Returns ``null`` if the activity has no snapshot yet (backend 404).
 * Other errors propagate as thrown ``Error``.
 */
export async function getActivityWeather(
  activityId: number,
  options: { raw?: boolean } = {}
): Promise<WeatherSnapshot | null> {
  const qs = options.raw ? "?raw=true" : "";
  return fetchOptionalJson<WeatherSnapshot>(
    `/activities/${activityId}/weather${qs}`
  );
}

/**
 * Kick off a weather-enrichment pass on the backend.
 */
export async function backfillWeather(
  params: { batch?: number; dry_run?: boolean } = {}
): Promise<WeatherBackfillResult> {
  return fetchJson<WeatherBackfillResult>("/weather/backfill", {
    method: "POST",
    body: JSON.stringify({
      batch: params.batch ?? 50,
      dry_run: params.dry_run ?? false,
    }),
  });
}
