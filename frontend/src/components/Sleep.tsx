import { useApi } from "../hooks/useApi";
import { fetchRecovery, type RecoveryRecord } from "../api/recovery";
import {
  fetchSleepSessions,
  fetchLatestSleepBySource,
  SleepSession,
} from "../api/sleep";
import { SleepRecoveryDetailsCard } from "./sleep/SleepRecoveryDetailsCard";

export default function Sleep() {
  const { data: sessions, loading: sessionsLoading } = useApi(
    ["sleep", "sessions", 30],
    () => fetchSleepSessions(30),
  );
  // Fetch the latest row for each source independently so the card binds
  // each column to its own provider (Eight Sleep usually leads Whoop by a
  // calendar day, so a global /sleep/latest hides Whoop most days).
  const { data: latestWhoop, loading: latestWhoopLoading } = useApi(
    ["sleep", "latest-by-source", "whoop"],
    () => fetchLatestSleepBySource("whoop"),
  );
  const { data: latestEight, loading: latestEightLoading } = useApi(
    ["sleep", "latest-by-source", "eight_sleep"],
    () => fetchLatestSleepBySource("eight_sleep"),
  );
  const { data: recoveryRows, loading: recoveryLoading } = useApi(
    ["recovery", "recent", 14],
    () => fetchRecovery(14),
  );

  if (
    sessionsLoading ||
    latestWhoopLoading ||
    latestEightLoading ||
    recoveryLoading
  ) {
    return <div className="loading">Loading sleep data...</div>;
  }

  // Merge list + latest endpoints so a row that only exists on /latest is still
  // visible to the pairing pass (edge race with sync timing).
  const sessionPool = mergeSleepSessions(sessions, latestWhoop, latestEight);
  const { whoopSleep: cardWhoop, eightSleep: cardEight } = resolveSleepPairForCard(
    sessionPool,
    latestWhoop,
    latestEight,
  );
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
