import { useMemo } from "react";
import { useApi } from "./useApi";
import { fetchSleepSessions, type SleepSession } from "../api/sleep";
import {
  fetchActivities,
  type ActivitySource,
  type ActivitySummary,
} from "../api/activities";
import {
  fetchStrengthSessions,
  type StrengthSession,
} from "../api/strength";

/**
 * Hooks that compute prev/next neighbors for detail pages. All hooks skip
 * days with no data (sparse-aware) and disable the corresponding arrow when
 * the user is already at the first or last record.
 *
 * Implementation note: each hook keeps the data-fetching pattern consistent
 * with the rest of the app — `useApi` (react-query) with a stable cache key
 * — so the list is shared across the surfaces that already display it.
 */

const ONE_DAY_MS = 24 * 60 * 60 * 1000;
const TWO_SOURCE_PAIR_WINDOW_DAYS = 1;

interface SleepNeighbors {
  prevDate: string | null;
  nextDate: string | null;
  loading: boolean;
}

/** ISO calendar date (YYYY-MM-DD) plus/minus whole days in UTC. */
function addDaysIso(isoDate: string, deltaDays: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const t = Date.UTC(y, m - 1, d + deltaDays);
  return new Date(t).toISOString().slice(0, 10);
}

/**
 * Collapse WHOOP + Eight Sleep rows that label the same physical night with
 * ±1 calendar day into a single canonical date. WHOOP keys nights by wake
 * date; Eight Sleep can sit ±1 day depending on timezone / API semantics.
 *
 * Strategy: walk every (date, source) row newest-first. For each row whose
 * source hasn't yet been claimed by an already-emitted canonical night
 * within ±`TWO_SOURCE_PAIR_WINDOW_DAYS`, emit it as a new night and claim
 * the closest unclaimed neighbor from each *other* source as the same
 * night. Same-source rows on different dates therefore stay separate (a
 * WHOOP-only run of consecutive nights produces one night per row), while
 * a WHOOP+Eight pair off-by-one collapses to a single night.
 *
 * Exposed for tests via the public hook surface; the returned list is
 * sorted **descending** by date.
 */
export function collapseSleepSessionsToNights(
  sessions: SleepSession[],
): string[] {
  if (sessions.length === 0) return [];

  // Build per-source date sets so neighbor lookup is O(1).
  const datesBySource = new Map<string, Set<string>>();
  for (const s of sessions) {
    if (!s.date) continue;
    const set = datesBySource.get(s.source) ?? new Set<string>();
    set.add(s.date);
    datesBySource.set(s.source, set);
  }

  // Track which (source, date) pairs have already been folded into some
  // canonical night so we don't emit them again.
  const claimed = new Map<string, Set<string>>();
  for (const src of datesBySource.keys()) claimed.set(src, new Set());

  // Walk every row newest-first; ordering is stable on date desc, source
  // alpha — but that's fine because we always check `claimed` before emitting.
  const allRows = sessions
    .filter((s) => Boolean(s.date))
    .map((s) => ({ date: s.date, source: s.source }))
    .sort((a, b) => {
      const byDate = b.date.localeCompare(a.date);
      return byDate !== 0 ? byDate : a.source.localeCompare(b.source);
    });

  const canonicalNights: string[] = [];

  for (const { date, source } of allRows) {
    if (claimed.get(source)!.has(date)) continue;

    // Emit this row as a new canonical night.
    canonicalNights.push(date);
    claimed.get(source)!.add(date);

    // Try to absorb one neighbor (±0 first, then ±1) from each OTHER source
    // into the same night. ±0 catches exact matches, ±1 catches the
    // off-by-one labelling case.
    for (const otherSource of datesBySource.keys()) {
      if (otherSource === source) continue;
      const otherDates = datesBySource.get(otherSource)!;
      const otherClaimed = claimed.get(otherSource)!;
      for (const off of [0, -1, 1] as const) {
        const candidate = off === 0 ? date : addDaysIso(date, off);
        if (otherDates.has(candidate) && !otherClaimed.has(candidate)) {
          otherClaimed.add(candidate);
          break;
        }
      }
    }
  }

  // Defensive: stable descending order.
  return canonicalNights.sort((a, b) => b.localeCompare(a));
}

/**
 * Locate the index in `descendingNights` that matches `currentDate`. The
 * match is tolerant: if the exact `currentDate` is not in the canonical
 * night list (e.g. user pinned a `?date=` from one source but the canonical
 * night collapsed onto the other source's date), pick the closest by
 * absolute day distance.
 */
function indexForCurrentNight(
  descendingNights: string[],
  currentDate: string | undefined,
): number {
  if (descendingNights.length === 0) return -1;
  if (!currentDate) return 0; // "latest" — treat newest as current

  const direct = descendingNights.indexOf(currentDate);
  if (direct >= 0) return direct;

  // Fall back to the closest night within the pairing window.
  let bestIdx = -1;
  let bestDist = Number.POSITIVE_INFINITY;
  const target = Date.UTC(
    Number(currentDate.slice(0, 4)),
    Number(currentDate.slice(5, 7)) - 1,
    Number(currentDate.slice(8, 10)),
  );
  for (let i = 0; i < descendingNights.length; i++) {
    const n = descendingNights[i];
    const t = Date.UTC(
      Number(n.slice(0, 4)),
      Number(n.slice(5, 7)) - 1,
      Number(n.slice(8, 10)),
    );
    const distDays = Math.abs(t - target) / ONE_DAY_MS;
    if (distDays <= TWO_SOURCE_PAIR_WINDOW_DAYS && distDays < bestDist) {
      bestIdx = i;
      bestDist = distDays;
    }
  }
  return bestIdx;
}

/**
 * Compute prev/next neighbor nights for the Sleep & Recovery detail page.
 *
 * - `currentDate` undefined → treat the latest known night as current
 *   (next is disabled, prev jumps to the second-newest night).
 * - WHOOP + Eight rows that label the same physical night with ±1 calendar
 *   day are collapsed into a single canonical night so the user only sees
 *   one "step" between distinct sleeps.
 */
export function useSleepNeighbors(
  currentDate: string | undefined,
): SleepNeighbors {
  const { data, loading } = useApi(
    ["sleep", "sessions", 365],
    () => fetchSleepSessions(365),
  );

  const sessions = data ?? [];
  const descendingNights = useMemo(
    () => collapseSleepSessionsToNights(sessions),
    [sessions],
  );

  return useMemo(() => {
    if (loading || descendingNights.length === 0) {
      return { prevDate: null, nextDate: null, loading };
    }
    const idx = indexForCurrentNight(descendingNights, currentDate);
    if (idx < 0) {
      // current date doesn't fall within our list — disable both arrows.
      return { prevDate: null, nextDate: null, loading: false };
    }
    // Descending order: index+1 is older (prev), index-1 is newer (next).
    const prevDate =
      idx + 1 < descendingNights.length ? descendingNights[idx + 1] : null;
    const nextDate = idx - 1 >= 0 ? descendingNights[idx - 1] : null;
    return { prevDate, nextDate, loading: false };
  }, [loading, descendingNights, currentDate]);
}

interface ActivityNeighborRef {
  id: number;
  source: ActivitySource;
}

interface ActivityNeighbors {
  prev: ActivityNeighborRef | null;
  next: ActivityNeighborRef | null;
  loading: boolean;
}

function resolveActivitySource(
  activity: ActivitySummary,
): ActivitySource {
  // Backend rows usually carry an explicit source; default to strava for
  // legacy rows that predate the multi-source schema.
  return activity.source ?? "strava";
}

/**
 * Compute prev/next neighbor activities across Strava + Apple workouts.
 * Matches the current row by `(id, source)` because Apple Health and Strava
 * id spaces overlap; matching on id alone would cross-link unrelated rows.
 */
export function useActivityNeighbors(
  currentId: number,
  currentSource: ActivitySource | null,
): ActivityNeighbors {
  const { data, loading } = useApi(
    ["activities", "list", 365, 500],
    () => fetchActivities({ days: 365, limit: 500 }),
  );

  return useMemo(() => {
    const rows = data ?? [];
    if (loading || rows.length === 0) {
      return { prev: null, next: null, loading };
    }
    // Descending by start_date_local so "next" (newer) is index-1.
    const sorted = [...rows].sort((a, b) => {
      const ad = a.start_date_local ?? "";
      const bd = b.start_date_local ?? "";
      return bd.localeCompare(ad);
    });
    const idx = sorted.findIndex((row) => {
      if (row.id !== currentId) return false;
      const rowSource = resolveActivitySource(row);
      // If caller didn't pin a source, accept any match on id (legacy URLs).
      if (currentSource == null) return true;
      return rowSource === currentSource;
    });
    if (idx < 0) {
      return { prev: null, next: null, loading: false };
    }
    const toRef = (row: ActivitySummary | undefined): ActivityNeighborRef | null =>
      row
        ? { id: row.id, source: resolveActivitySource(row) }
        : null;
    return {
      prev: toRef(sorted[idx + 1]),
      next: toRef(sorted[idx - 1]),
      loading: false,
    };
  }, [data, loading, currentId, currentSource]);
}

interface LiftingNeighbors {
  prevDate: string | null;
  nextDate: string | null;
  loading: boolean;
}

/**
 * Compute prev/next neighbor lifting session dates. Strength sessions are
 * one row per calendar date, so the list is already sparse and dedupes
 * naturally.
 */
export function useLiftingNeighbors(
  currentDate: string,
): LiftingNeighbors {
  const { data, loading } = useApi(
    ["strength", "sessions", 500],
    () => fetchStrengthSessions(500),
  );

  return useMemo(() => {
    const rows = data ?? [];
    if (loading || rows.length === 0) {
      return { prevDate: null, nextDate: null, loading };
    }
    const sorted: StrengthSession[] = [...rows].sort((a, b) =>
      b.date.localeCompare(a.date),
    );
    const idx = sorted.findIndex((row) => row.date === currentDate);
    if (idx < 0) {
      return { prevDate: null, nextDate: null, loading: false };
    }
    const prevDate =
      idx + 1 < sorted.length ? sorted[idx + 1].date : null;
    const nextDate = idx - 1 >= 0 ? sorted[idx - 1].date : null;
    return { prevDate, nextDate, loading: false };
  }, [data, loading, currentDate]);
}
