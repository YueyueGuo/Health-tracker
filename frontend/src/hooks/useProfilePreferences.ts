import { useCallback, useEffect, useState } from "react";
import { fetchProfile, patchProfile } from "../api/profile";
import { getErrorMessage } from "../utils/errors";

export const PROFILE_PREFERENCES_STORAGE_KEY = "ht.profilePreferences.v1";

export const FOCUS_OPTIONS = [
  "General Fitness",
  "Endurance Base",
  "Event Prep",
  "Strength & Size",
  "Active Recovery",
] as const;

export const FREQUENCY_OPTIONS = [
  "1-2 Days/wk",
  "3 Days/wk",
  "4-5 Days/wk",
  "6+ Days/wk",
] as const;

export const DURATION_OPTIONS = ["< 45m", "45-60m", "60-90m", "90m+"] as const;

export const EQUIPMENT_OPTIONS = [
  "Full Gym",
  "Dumbbells",
  "Kettlebells",
  "Pull-up Bar",
  "Running Shoes",
  "Bicycle",
  "Pool",
] as const;

export const LIMITATION_OPTIONS = [
  "None",
  "Knee Pain",
  "Lower Back",
  "Shoulder",
  "Ankle/Foot",
  "Low Impact Only",
] as const;

export type TrainingFocus = (typeof FOCUS_OPTIONS)[number];
export type TrainingFrequency = (typeof FREQUENCY_OPTIONS)[number];
export type TrainingDuration = (typeof DURATION_OPTIONS)[number];
export type EquipmentOption = (typeof EQUIPMENT_OPTIONS)[number];
export type LimitationOption = (typeof LIMITATION_OPTIONS)[number];

export interface ProfileVitals {
  age: string;
  weight: string;
  height: string;
  maxHr: string;
  lthr: string;
}

export interface ProfilePreferences {
  displayName: string;
  email: string;
  focus: TrainingFocus;
  frequency: TrainingFrequency;
  duration: TrainingDuration;
  equipment: EquipmentOption[];
  limitations: LimitationOption[];
  vitals: ProfileVitals;
}

export const DEFAULT_PROFILE_PREFERENCES: ProfilePreferences = {
  displayName: "",
  email: "",
  focus: "Event Prep",
  frequency: "4-5 Days/wk",
  duration: "45-60m",
  equipment: ["Full Gym", "Running Shoes", "Bicycle"],
  limitations: ["Low Impact Only"],
  vitals: {
    age: "32",
    weight: "175",
    height: "5'10\"",
    maxHr: "192",
    lthr: "174",
  },
};

export function normalizeLimitations(items: LimitationOption[]): LimitationOption[] {
  if (items.includes("None")) return ["None"];
  return items.length > 0 ? items : ["None"];
}

/** Local-first backup when `/api/profile` is unavailable */
export function loadProfilePreferences(): ProfilePreferences {
  if (typeof window === "undefined") return DEFAULT_PROFILE_PREFERENCES;

  try {
    const raw = window.localStorage.getItem(PROFILE_PREFERENCES_STORAGE_KEY);
    if (!raw) return DEFAULT_PROFILE_PREFERENCES;
    return parseProfilePreferences(JSON.parse(raw));
  } catch {
    return DEFAULT_PROFILE_PREFERENCES;
  }
}

/** Mirror backend + local-first backup after successful save */
export function saveProfilePreferences(preferences: ProfilePreferences): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(
    PROFILE_PREFERENCES_STORAGE_KEY,
    JSON.stringify(preferences)
  );
}

export function useProfilePreferences() {
  const [preferences, setPreferences] = useState<ProfilePreferences>(() =>
    loadProfilePreferences()
  );
  const [loading, setLoading] = useState(true);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchProfile()
      .then((remote) => {
        const parsed = parseProfilePreferences(remote);
        if (!cancelled) {
          setPreferences(parsed);
          saveProfilePreferences(parsed);
          setSaveError(null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          const localOnly = loadProfilePreferences();
          setPreferences(localOnly);
          setSaveError(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = useCallback(
    async (next?: ProfilePreferences) => {
      const toSave = next ?? preferences;
      setSaveError(null);
      try {
        const result = await patchProfile(toSave);
        const parsed = parseProfilePreferences(result);
        saveProfilePreferences(parsed);
        setPreferences(parsed);
        setLastSavedAt(new Date().toISOString());
      } catch (e) {
        const message = getErrorMessage(e);
        saveProfilePreferences(toSave);
        setPreferences(toSave);
        setSaveError(message);
      }
    },
    [preferences]
  );

  return { preferences, setPreferences, save, loading, lastSavedAt, saveError };
}

export function parseProfilePreferences(value: unknown): ProfilePreferences {
  if (!isRecord(value)) return DEFAULT_PROFILE_PREFERENCES;

  const defaults = DEFAULT_PROFILE_PREFERENCES;
  const vitals = isRecord(value.vitals) ? value.vitals : {};

  return {
    displayName: readString(value.displayName, defaults.displayName),
    email: readString(value.email, defaults.email),
    focus: readOption(value.focus, FOCUS_OPTIONS, defaults.focus),
    frequency: readOption(value.frequency, FREQUENCY_OPTIONS, defaults.frequency),
    duration: readOption(value.duration, DURATION_OPTIONS, defaults.duration),
    equipment: readOptions(value.equipment, EQUIPMENT_OPTIONS, defaults.equipment),
    limitations: normalizeLimitations(
      readOptions(value.limitations, LIMITATION_OPTIONS, defaults.limitations)
    ),
    vitals: {
      age: readString(vitals.age, defaults.vitals.age),
      weight: readString(vitals.weight, defaults.vitals.weight),
      height: readString(vitals.height, defaults.vitals.height),
      maxHr: readString(vitals.maxHr, defaults.vitals.maxHr),
      lthr: readString(vitals.lthr, defaults.vitals.lthr),
    },
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function readOption<T extends string>(
  value: unknown,
  options: readonly T[],
  fallback: T
): T {
  return typeof value === "string" && options.includes(value as T)
    ? (value as T)
    : fallback;
}

function readOptions<T extends string>(
  value: unknown,
  options: readonly T[],
  fallback: readonly T[]
): T[] {
  if (!Array.isArray(value)) return [...fallback];

  const allowed = new Set(options);
  const parsed = value.filter((item): item is T => allowed.has(item as T));
  return parsed.length > 0 ? parsed : [...fallback];
}
