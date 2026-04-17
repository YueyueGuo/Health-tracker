/**
 * Unit system context + formatters.
 *
 * Two user-selectable systems, persisted in localStorage:
 *   - "imperial" (default): miles, ft, mph / min-per-mile, °F
 *   - "metric":             km,    m,  m/s / min-per-km,    °C
 *
 * Short distances (< 1 mile when imperial, < 1 km when metric) are
 * always rendered in meters so interval splits like 200m / 400m / 800m
 * read naturally regardless of the system setting.
 *
 * All formatters are pure functions exported alongside the hook so
 * non-React code paths can reuse them (e.g. tooltips built inside a
 * Recharts callback that doesn't have easy hook access).
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type UnitSystem = "imperial" | "metric";

const STORAGE_KEY = "ht.units";
const DEFAULT_UNITS: UnitSystem = "imperial";

// Conversion constants
const METERS_PER_MILE = 1609.344;
const FEET_PER_METER = 3.28084;

// ── Formatters ──────────────────────────────────────────────────────

/** Format a distance in meters. Short distances always render in meters. */
export function formatDistance(
  meters: number | null | undefined,
  units: UnitSystem
): string {
  if (meters == null) return "—";
  if (units === "imperial") {
    // Anything under a mile → meters (interval splits: 200m, 400m, 800m).
    if (meters < METERS_PER_MILE) return `${Math.round(meters)} m`;
    return `${(meters / METERS_PER_MILE).toFixed(2)} mi`;
  }
  // Metric: under 1 km → meters.
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(2)} km`;
}

/** Short distance — used in summary contexts that want fewer decimals. */
export function formatDistanceShort(
  meters: number | null | undefined,
  units: UnitSystem
): string {
  if (meters == null) return "—";
  if (units === "imperial") {
    if (meters < METERS_PER_MILE) return `${Math.round(meters)} m`;
    return `${(meters / METERS_PER_MILE).toFixed(1)} mi`;
  }
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(1)} km`;
}

/**
 * Format pace (time per unit distance) for running-style activities.
 * Input is speed in m/s (Strava/Open-Meteo convention).
 */
export function formatPace(
  speedMps: number | null | undefined,
  units: UnitSystem
): string {
  if (!speedMps || speedMps <= 0) return "—";
  const secondsPerUnit =
    units === "imperial" ? METERS_PER_MILE / speedMps : 1000 / speedMps;
  const mins = Math.floor(secondsPerUnit / 60);
  const secs = Math.round(secondsPerUnit % 60);
  const suffix = units === "imperial" ? "/mi" : "/km";
  return `${mins}:${secs.toString().padStart(2, "0")} ${suffix}`;
}

/**
 * Format speed (distance per unit time) for cycling-style activities.
 * Input is speed in m/s.
 */
export function formatSpeed(
  speedMps: number | null | undefined,
  units: UnitSystem
): string {
  if (!speedMps || speedMps <= 0) return "—";
  if (units === "imperial") {
    const mph = (speedMps * 3600) / METERS_PER_MILE;
    return `${mph.toFixed(1)} mph`;
  }
  const kph = (speedMps * 3600) / 1000;
  return `${kph.toFixed(1)} km/h`;
}

export function formatElevation(
  meters: number | null | undefined,
  units: UnitSystem
): string {
  if (meters == null) return "—";
  if (units === "imperial") {
    return `${Math.round(meters * FEET_PER_METER)} ft`;
  }
  return `${Math.round(meters)} m`;
}

export function formatTemperature(
  celsius: number | null | undefined,
  units: UnitSystem
): string {
  if (celsius == null) return "—";
  if (units === "imperial") {
    return `${Math.round(celsius * (9 / 5) + 32)}°F`;
  }
  return `${Math.round(celsius)}°C`;
}

export function formatWindSpeed(
  mps: number | null | undefined,
  units: UnitSystem
): string {
  if (mps == null) return "—";
  if (units === "imperial") {
    const mph = (mps * 3600) / METERS_PER_MILE;
    return `${mph.toFixed(1)} mph`;
  }
  return `${mps.toFixed(1)} m/s`;
}

/**
 * Cycling sports show speed; running/hiking show pace. Fall back to pace
 * for anything that looks like an on-foot activity.
 */
const CYCLING_SPORTS = new Set([
  "ride",
  "virtualride",
  "ebikeride",
  "handcycle",
  "mountainbikeride",
  "gravelride",
  "velomobile",
]);

export function isCyclingSport(sportType: string | null | undefined): boolean {
  if (!sportType) return false;
  return CYCLING_SPORTS.has(sportType.toLowerCase());
}

export function formatPaceOrSpeed(
  speedMps: number | null | undefined,
  sportType: string | null | undefined,
  units: UnitSystem
): string {
  if (isCyclingSport(sportType)) return formatSpeed(speedMps, units);
  return formatPace(speedMps, units);
}

// ── Context ─────────────────────────────────────────────────────────

interface UnitsContextValue {
  units: UnitSystem;
  setUnits: (u: UnitSystem) => void;
  toggle: () => void;
}

const UnitsContext = createContext<UnitsContextValue | null>(null);

function readStoredUnits(): UnitSystem {
  if (typeof window === "undefined") return DEFAULT_UNITS;
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === "imperial" || v === "metric") return v;
  } catch {
    // localStorage may be unavailable (SSR / privacy modes); fall back.
  }
  return DEFAULT_UNITS;
}

export function UnitsProvider({ children }: { children: ReactNode }) {
  const [units, setUnitsState] = useState<UnitSystem>(readStoredUnits);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, units);
    } catch {
      // no-op
    }
  }, [units]);

  const setUnits = useCallback((u: UnitSystem) => setUnitsState(u), []);
  const toggle = useCallback(
    () => setUnitsState((u) => (u === "imperial" ? "metric" : "imperial")),
    []
  );

  const value = useMemo(
    () => ({ units, setUnits, toggle }),
    [units, setUnits, toggle]
  );

  return <UnitsContext.Provider value={value}>{children}</UnitsContext.Provider>;
}

export function useUnits(): UnitsContextValue {
  const ctx = useContext(UnitsContext);
  if (!ctx) {
    throw new Error("useUnits must be used inside a UnitsProvider");
  }
  return ctx;
}
