import { useEffect, useState } from "react";
import {
  fetchStrengthProgression,
  type ProgressionPoint,
} from "../../api/strength";
import { formatWeight, useUnits } from "../../hooks/useUnits";

const KG_TO_LB = 2.20462;

/** Looks up the most-recent recorded session for a named exercise.
 *  Returns a short caption like:
 *    "Last (Apr 12): top set 8 reps @ 132 lb · est 1RM 165.0 lb"
 *  (or kg when the user is on metric units).
 *  Debounced 300ms so we don't fire a request on every keystroke. */
export function usePriorPerformance(name: string): string | null {
  const { units } = useUnits();
  const trimmed = name.trim();
  const [point, setPoint] = useState<ProgressionPoint | null>(null);
  const [lookedUpName, setLookedUpName] = useState<string | null>(null);

  useEffect(() => {
    if (!trimmed) {
      setPoint(null);
      setLookedUpName(null);
      return;
    }
    if (trimmed === lookedUpName) return;
    let cancelled = false;
    const handle = window.setTimeout(async () => {
      try {
        const history = await fetchStrengthProgression(trimmed, 180);
        if (cancelled) return;
        setPoint(history.length > 0 ? history[history.length - 1] : null);
        setLookedUpName(trimmed);
      } catch {
        if (cancelled) return;
        setPoint(null);
        setLookedUpName(trimmed);
      }
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [trimmed, lookedUpName]);

  if (!point || lookedUpName !== trimmed) return null;
  const date = new Date(point.date + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
  const weight =
    point.max_weight_kg > 0
      ? ` @ ${formatWeight(point.max_weight_kg * KG_TO_LB, units)}`
      : "";
  const oneRm =
    point.est_1rm_kg > 0
      ? ` · est 1RM ${formatWeight(point.est_1rm_kg * KG_TO_LB, units, { digits: 1 })}`
      : "";
  return `Last (${date}): top set ${point.top_set_reps} reps${weight}${oneRm}`;
}
