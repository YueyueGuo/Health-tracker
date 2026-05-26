/**
 * Display helpers for the shoes feature.
 *
 * Distances on the wire are meters; we convert here using the active
 * `useUnits` system. Form inputs accept the user's preferred unit and
 * convert to meters before POST/PATCH via `parseDistanceInput`.
 */
import type { UnitSystem } from "../hooks/useUnits";

const METERS_PER_MILE = 1609.344;
const METERS_PER_KM = 1000;

/**
 * Format a shoe distance (cumulative mileage, lifespan target) in the
 * active unit system. Shoes always have miles or kilometers as the
 * natural unit — there is no useful sub-mile rendering, unlike
 * `formatDistance` from `useUnits` which switches to meters under the
 * unit threshold.
 */
export function formatShoeDistance(
  meters: number | null | undefined,
  units: UnitSystem,
): string {
  if (meters == null) return "—";
  if (units === "imperial") {
    const mi = meters / METERS_PER_MILE;
    return `${roundToOne(mi)} mi`;
  }
  const km = meters / METERS_PER_KM;
  return `${roundToOne(km)} km`;
}

/**
 * Format a percent-used reading. `null` (no lifespan target set) shows
 * "—"; values above 100 are passed through so the UI can render
 * "120%" for an overdue shoe.
 */
export function formatPercentUsed(
  percent: number | null | undefined,
): string {
  if (percent == null) return "—";
  return `${Math.round(percent)}%`;
}

export type ProgressTone = "ok" | "warn" | "danger";

/**
 * Map a percent-used value onto the three-step color band the UI uses
 * for progress bars and chips:
 *   `<80`  ok     (neutral / green)
 *   `>=80` warn   (amber chip "Approaching end of life")
 *   `>=100` danger (red chip "Overdue — consider retiring")
 * Null targets fall through to "ok" so the bar stays visually neutral.
 */
export function progressTone(percent: number | null | undefined): ProgressTone {
  if (percent == null) return "ok";
  if (percent >= 100) return "danger";
  if (percent >= 80) return "warn";
  return "ok";
}

/**
 * Parse a UI-supplied distance string back into meters before POST.
 *
 * Accepts a free-form numeric (e.g. "500", "500.5") in the active
 * unit. Returns `null` on empty input (so callers can send `null` to
 * clear `total_usable_distance_m`); returns `undefined` when the input
 * is not a valid positive number.
 */
export function parseDistanceInput(
  value: string,
  units: UnitSystem,
): number | null | undefined {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n <= 0) return undefined;
  return units === "imperial" ? n * METERS_PER_MILE : n * METERS_PER_KM;
}

/**
 * Inverse of `parseDistanceInput`: convert a stored meters value back
 * into the user's unit for prefilling the form. Returns an empty
 * string when meters is null so the input shows the placeholder.
 */
export function metersToInput(
  meters: number | null | undefined,
  units: UnitSystem,
): string {
  if (meters == null) return "";
  const converted =
    units === "imperial" ? meters / METERS_PER_MILE : meters / METERS_PER_KM;
  // Trim trailing .0 for clean prefill: 500 not 500.0.
  const rounded = Math.round(converted * 100) / 100;
  return String(rounded);
}

export function unitLabel(units: UnitSystem): "mi" | "km" {
  return units === "imperial" ? "mi" : "km";
}

function roundToOne(value: number): string {
  // Hide the trailing .0 when it lands on an integer so "5.0 mi" reads "5 mi".
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}
