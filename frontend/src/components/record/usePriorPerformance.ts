import { useEffect, useState } from "react";
import {
  fetchStrengthProgression,
  type ProgressionPoint,
} from "../../api/strength";

/** Looks up the most-recent recorded session for a named exercise.
 *  Returns a short caption like:
 *    "Last (Apr 12): top set 8 reps @ 60 kg · est 1RM 75.0 kg"
 *  Debounced 300ms so we don't fire a request on every keystroke. */
export function usePriorPerformance(name: string): string | null {
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
  const weight = point.max_weight_kg > 0 ? ` @ ${point.max_weight_kg} kg` : "";
  const oneRm =
    point.est_1rm_kg > 0 ? ` · est 1RM ${point.est_1rm_kg.toFixed(1)} kg` : "";
  return `Last (${date}): top set ${point.top_set_reps} reps${weight}${oneRm}`;
}
