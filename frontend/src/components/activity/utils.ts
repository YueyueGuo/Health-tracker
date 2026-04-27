import type { UnitSystem } from "../../hooks/useUnits";

const METERS_PER_MILE = 1609.344;

/** mm:ss for splits, hh:mm:ss when ≥ 1h. */
export function formatHmsCompact(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Decimal minutes per mile/km — used as a numeric Y-axis value for charts. */
export function paceDecimal(
  mps: number | null | undefined,
  units: UnitSystem
): number | undefined {
  if (!mps || mps <= 0) return undefined;
  const metersPerUnit = units === "imperial" ? METERS_PER_MILE : 1000;
  return metersPerUnit / mps / 60;
}

/** Speed in mph or km/h. */
export function speedValue(
  mps: number | null | undefined,
  units: UnitSystem
): number | undefined {
  if (!mps || mps <= 0) return undefined;
  return units === "imperial"
    ? (mps * 3600) / METERS_PER_MILE
    : (mps * 3600) / 1000;
}

/** Format pace from m/s as "m:ss" without unit suffix (compact for tables). */
export function paceShort(
  mps: number | null | undefined,
  units: UnitSystem
): string {
  if (!mps || mps <= 0) return "—";
  const decimal = paceDecimal(mps, units);
  if (decimal == null) return "—";
  const m = Math.floor(decimal);
  const s = Math.round((decimal - m) * 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function speedShort(
  mps: number | null | undefined,
  units: UnitSystem
): string {
  const v = speedValue(mps, units);
  if (v == null) return "—";
  return v.toFixed(1);
}

export function paceUnitLabel(units: UnitSystem): string {
  return units === "imperial" ? "/mi" : "/km";
}

export function speedUnitLabel(units: UnitSystem): string {
  return units === "imperial" ? "mph" : "km/h";
}

export function distanceUnitLabel(units: UnitSystem): string {
  return units === "imperial" ? "mi" : "km";
}

export function elevationUnitLabel(units: UnitSystem): string {
  return units === "imperial" ? "ft" : "m";
}

export function metersToDisplay(
  meters: number | null | undefined,
  units: UnitSystem
): string {
  if (meters == null) return "—";
  if (units === "imperial") {
    return (meters / METERS_PER_MILE).toFixed(2);
  }
  return (meters / 1000).toFixed(2);
}

export function elevationToDisplay(
  meters: number | null | undefined,
  units: UnitSystem
): string {
  if (meters == null) return "—";
  if (units === "imperial") {
    return Math.round(meters * 3.28084).toLocaleString();
  }
  return Math.round(meters).toLocaleString();
}

/** Convert kilograms → display volume in pounds (mockup) or kg. */
export function formatVolumeWeight(
  kg: number | null | undefined,
  units: UnitSystem
): { value: string; unit: string } {
  if (kg == null) return { value: "—", unit: "" };
  if (units === "imperial") {
    return {
      value: Math.round(kg * 2.20462).toLocaleString(),
      unit: "lb",
    };
  }
  return { value: Math.round(kg).toLocaleString(), unit: "kg" };
}

/** "Mon, Apr 24 • 5:30 PM" */
export function formatActivityDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const datePart = d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const timePart = d.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  return `${datePart} • ${timePart}`;
}

/** Mockup HR-zone palette. Order = Z1..Z5. */
export const HR_ZONE_COLORS = [
  "#64748b", // Z1 Recovery
  "#34d399", // Z2 Aerobic
  "#fbbf24", // Z3 Tempo
  "#f97316", // Z4 Threshold
  "#fb7185", // Z5 Anaerobic
];

export const HR_ZONE_LABELS = [
  "Recovery",
  "Aerobic",
  "Tempo",
  "Threshold",
  "Anaerobic",
];
