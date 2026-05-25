import { useSearchParams } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import { fetchRecovery, type RecoveryRecord } from "../api/recovery";
import {
  fetchSleepSessions,
  fetchLatestSleep,
  SleepSession,
} from "../api/sleep";
import { SleepRecoveryDetailsCard } from "./sleep/SleepRecoveryDetailsCard";

export default function Sleep() {
  // History deep-links (`/sleep?date=YYYY-MM-DD`) pin the page to that night.
  // The dashboard entry point (`/sleep` with no query) keeps the "latest"
  // semantics by leaving `dateParam` undefined. See
  // docs/bugs/sleep-detail-date-scope.md.
  const [searchParams] = useSearchParams();
  // Normalize empty-string (`/sleep?date=`) to undefined so the fetcher omits
  // `on_or_before=` rather than sending an empty value (backend 422).
  const dateParam = searchParams.get("date") || undefined;

  const { data: sessions, loading: sessionsLoading } = useApi(
    ["sleep", "sessions", 30],
    () => fetchSleepSessions(30),
  );
  // Fetch the latest row for each source independently so the card binds
  // each column to its own provider (Eight Sleep usually leads Whoop by a
  // calendar day, so a global /sleep/latest hides Whoop most days).
  // The date is included in the cache key so navigating between historical
  // nights does not return the previous night's cached payload.
  const { data: latestWhoop, loading: latestWhoopLoading } = useApi(
    ["sleep", "latest", "whoop", dateParam ?? "latest"],
    () => fetchLatestSleep({ source: "whoop", onOrBefore: dateParam }),
  );
  const { data: latestEight, loading: latestEightLoading } = useApi(
    ["sleep", "latest", "eight_sleep", dateParam ?? "latest"],
    () => fetchLatestSleep({ source: "eight_sleep", onOrBefore: dateParam }),
  );
  // Widened lookback (30 vs 14) gives deep-linked nights a better chance of
  // finding their matching recovery row. `asOf` anchors the window when a
  // date is present so the recent recovery rows are scoped to that night.
  // The full date-anchored pairing pass is tracked under the
  // out-of-scope cleanup in docs/bugs/sleep-detail-date-scope.md.
  const { data: recoveryRows, loading: recoveryLoading } = useApi(
    ["recovery", "recent", 30, dateParam ?? "latest"],
    () => fetchRecovery(30, dateParam),
  );

  if (
    sessionsLoading ||
    latestWhoopLoading ||
    latestEightLoading ||
    recoveryLoading
  ) {
    return <div className="loading">Loading sleep data...</div>;
  }

  // When deep-linked to a specific night (`?date=`), the date-scoped
  // `/sleep/latest?on_or_before=…` responses already describe that night for
  // each provider, so use them directly. Walking the pool newest-first would
  // hand back the newest pair instead — see issue #51 / qa-verifier round 2.
  //
  // Without `dateParam` (dashboard entry point) we keep the pairing pass so
  // WHOOP+Eight rows that label the same night with ±1 calendar days still
  // line up.
  let cardWhoop: SleepSession | null;
  let cardEight: SleepSession | null;
  if (dateParam) {
    cardWhoop = latestWhoop ?? null;
    cardEight = latestEight ?? null;
  } else {
    // Merge list + latest endpoints so a row that only exists on /latest is
    // still visible to the pairing pass (edge race with sync timing).
    const sessionPool = mergeSleepSessions(sessions, latestWhoop, latestEight);
    const pair = resolveSleepPairForCard(sessionPool, latestWhoop, latestEight);
    cardWhoop = pair.whoopSleep;
    cardEight = pair.eightSleep;
  }
  const cardRecovery = pickRecoveryForSleeps(
    recoveryRows,
    cardWhoop?.date,
    cardEight?.date,
  );

  return (
    <div className="pb-8 space-y-4">
      <SleepRecoveryDetailsCard
        whoopSleep={cardWhoop}
        eightSleep={cardEight}
        recovery={cardRecovery}
      />
    </div>
  );
}

/** ISO calendar date (YYYY-MM-DD) plus/minus whole days in UTC. */
function addDaysIso(isoDate: string, deltaDays: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const t = Date.UTC(y, m - 1, d + deltaDays);
  return new Date(t).toISOString().slice(0, 10);
}

function mergeSleepSessions(
  list: SleepSession[] | null | undefined,
  latestWhoop: SleepSession | null | undefined,
  latestEight: SleepSession | null | undefined,
): SleepSession[] {
  const out = [...(list ?? [])];
  for (const extra of [latestWhoop, latestEight]) {
    if (extra && !out.some((r) => r.id === extra.id)) out.push(extra);
  }
  return out;
}

function findEightForWhoopNight(
  pool: SleepSession[],
  whoop: SleepSession,
): SleepSession | null {
  // WHOOP keys nights by wake (end) date; Eight Sleep trend ``day`` is often
  // the same calendar day but can sit ±1 day depending on timezone / API
  // semantics. Try same day first, then neighbors.
  for (const off of [0, -1, 1] as const) {
    const d = addDaysIso(whoop.date, off);
    const hit = pool.find((r) => r.source === "eight_sleep" && r.date === d);
    if (hit) return hit;
  }
  return null;
}

function findWhoopForEightNight(
  pool: SleepSession[],
  eight: SleepSession,
): SleepSession | null {
  for (const off of [0, -1, 1] as const) {
    const d = addDaysIso(eight.date, off);
    const hit = pool.find((r) => r.source === "whoop" && r.date === d);
    if (hit) return hit;
  }
  return null;
}

/**
 * Pick WHOOP + Eight Sleep rows that describe the *same* physical night.
 * ``/sleep/latest?source=…`` alone compares unrelated calendar rows when the
 * two vendors label wake night differently; this walks recent WHOOP nights
 * (newest first) until an Eight row lines up on the same day or ±1.
 */
function resolveSleepPairForCard(
  pool: SleepSession[],
  latestWhoop: SleepSession | null | undefined,
  latestEight: SleepSession | null | undefined,
): { whoopSleep: SleepSession | null; eightSleep: SleepSession | null } {
  const whoopRows = pool
    .filter((r) => r.source === "whoop")
    .sort((a, b) => b.date.localeCompare(a.date));
  for (const w of whoopRows) {
    const e = findEightForWhoopNight(pool, w);
    if (e) return { whoopSleep: w, eightSleep: e };
  }
  const eightRows = pool
    .filter((r) => r.source === "eight_sleep")
    .sort((a, b) => b.date.localeCompare(a.date));
  for (const e of eightRows) {
    const w = findWhoopForEightNight(pool, e);
    if (w) return { whoopSleep: w, eightSleep: e };
  }
  return {
    whoopSleep: latestWhoop ?? null,
    eightSleep: latestEight ?? null,
  };
}

/** WHOOP recovery rows are keyed by cycle day — try ±1 around each sleep date. */
function pickRecoveryForSleeps(
  rows: RecoveryRecord[] | null | undefined,
  whoopNight: string | null | undefined,
  eightNight: string | null | undefined,
): RecoveryRecord | null {
  if (!rows?.length) return null;
  const tryDates: string[] = [];
  for (const base of [whoopNight, eightNight]) {
    if (!base) continue;
    for (const off of [0, -1, 1] as const) {
      tryDates.push(addDaysIso(base, off));
    }
  }
  const seen = new Set<string>();
  for (const d of tryDates) {
    if (seen.has(d)) continue;
    seen.add(d);
    const hit = rows.find((r) => r.date === d);
    if (hit) return hit;
  }
  return rows[0] ?? null;
}
