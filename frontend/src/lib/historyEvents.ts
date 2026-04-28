import type { ActivitySummary } from "../api/activities";
import type { SleepSession } from "../api/sleep";
import type { StrengthSession } from "../api/strength";

type EventCategory = "Workout" | "Health";
export type EventType =
  | "Ride"
  | "Run"
  | "Strength"
  | "Hike"
  | "Walk"
  | "Other"
  | "MorningStatus";

interface EventMetric {
  label: string;
  value: string;
  /** Tailwind text-color class. Omit for default white. */
  colorClass?: string;
}

export interface HistoryEvent {
  id: string;
  category: EventCategory;
  type: EventType;
  title: string;
  /** ISO datetime used for sort + relative-date subtitle. */
  timestamp: string;
  /** True when the event represents a low-recovery night and should be
   *  rendered with the amber callout treatment. */
  highlight?: boolean;
  /** Metrics shown as small chips below the title. */
  metrics: EventMetric[];
  /** When tapped: where to navigate. Null for events with no detail page yet. */
  navigateTo: string | null;
}

export type FilterId = "All" | "Workout" | "Health" | "Ride" | "Run" | "Strength";

export const FILTERS: { id: FilterId; label: string }[] = [
  { id: "All", label: "All" },
  { id: "Workout", label: "Workouts" },
  { id: "Health", label: "Health & Sleep" },
  { id: "Ride", label: "Rides" },
  { id: "Run", label: "Runs" },
  { id: "Strength", label: "Strength" },
];

const RIDE_SPORTS = new Set([
  "Ride",
  "VirtualRide",
  "EBikeRide",
  "MountainBikeRide",
  "GravelRide",
]);
const RUN_SPORTS = new Set(["Run", "VirtualRun", "TrailRun"]);
const HIKE_SPORTS = new Set(["Hike"]);
const WALK_SPORTS = new Set(["Walk"]);

export function classifyActivity(sport_type: string | null): EventType {
  if (!sport_type) return "Other";
  if (sport_type === "WeightTraining") return "Strength";
  if (RIDE_SPORTS.has(sport_type)) return "Ride";
  if (RUN_SPORTS.has(sport_type)) return "Run";
  if (HIKE_SPORTS.has(sport_type)) return "Hike";
  if (WALK_SPORTS.has(sport_type)) return "Walk";
  return "Other";
}

function formatDuration(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatDistanceMi(meters: number | null | undefined): string {
  if (!meters) return "—";
  const mi = meters / 1609.34;
  return `${mi.toFixed(1)} mi`;
}

function formatPaceMinPerMi(speed_mps: number | null | undefined): string {
  if (!speed_mps || speed_mps <= 0) return "—";
  const minPerMi = 26.8224 / speed_mps;
  const m = Math.floor(minPerMi);
  const s = Math.round((minPerMi - m) * 60);
  return `${m}:${String(s).padStart(2, "0")}/mi`;
}

function formatVolume(kg: number | null | undefined): string {
  if (!kg) return "—";
  const lb = kg * 2.20462;
  return `${Math.round(lb).toLocaleString()} lb`;
}

function activityTimestamp(a: ActivitySummary): string | null {
  return a.start_date_local || a.start_date;
}

function sleepTimestamp(s: SleepSession): string {
  return s.wake_time || `${s.date}T07:00:00`;
}

function activityToEvent(a: ActivitySummary): HistoryEvent {
  const type = classifyActivity(a.sport_type);
  const ts = activityTimestamp(a) || `${(a.start_date_local || "").slice(0, 10) || "1970-01-01"}T12:00:00`;
  const metrics: EventMetric[] = [];
  if (type === "Ride") {
    metrics.push({ label: "Distance", value: formatDistanceMi(a.distance) });
    metrics.push({ label: "Time", value: formatDuration(a.moving_time) });
    metrics.push({
      label: "TSS",
      value: a.suffer_score != null ? Math.round(a.suffer_score).toString() : "—",
    });
    metrics.push({
      label: "Avg HR",
      value: a.average_hr != null ? Math.round(a.average_hr).toString() : "—",
    });
  } else if (type === "Run" || type === "Walk" || type === "Hike") {
    metrics.push({ label: "Distance", value: formatDistanceMi(a.distance) });
    metrics.push({ label: "Time", value: formatDuration(a.moving_time) });
    metrics.push({ label: "Pace", value: formatPaceMinPerMi(a.average_speed) });
    if (a.average_hr != null) {
      metrics.push({ label: "Avg HR", value: Math.round(a.average_hr).toString() });
    }
  } else {
    metrics.push({ label: "Time", value: formatDuration(a.moving_time) });
    if (a.average_hr != null) {
      metrics.push({ label: "Avg HR", value: Math.round(a.average_hr).toString() });
    }
    if (a.suffer_score != null) {
      metrics.push({ label: "RE", value: Math.round(a.suffer_score).toString() });
    }
  }
  return {
    id: `activity-${a.id}`,
    category: "Workout",
    type,
    title: a.name,
    timestamp: ts,
    metrics,
    navigateTo: `/activities/${a.id}`,
  };
}

function strengthToEvent(s: StrengthSession): HistoryEvent {
  return {
    id: `strength-${s.date}`,
    category: "Workout",
    type: "Strength",
    title: "Strength Session",
    timestamp: `${s.date}T12:00:00`,
    metrics: [
      { label: "Volume", value: formatVolume(s.total_volume_kg) },
      { label: "Sets", value: s.total_sets.toString() },
      { label: "Exercises", value: s.exercise_count.toString() },
    ],
    // Strength rows route to the linked Strava activity when available;
    // otherwise we have no detail page (post-hoc linking is deferred).
    navigateTo: s.activity_id != null ? `/activities/${s.activity_id}` : null,
  };
}

function sleepToEvent(s: SleepSession): HistoryEvent {
  const recovery = s.sleep_fitness_score;
  const score = s.sleep_score;
  const hrv = s.hrv;
  const totalMin = s.total_duration;
  const lowRecovery = recovery != null && recovery < 50;
  const recoveryColor =
    recovery == null
      ? undefined
      : lowRecovery
      ? "text-brand-amber"
      : "text-brand-green";
  const scoreColor =
    score == null
      ? undefined
      : score < 50
      ? "text-brand-amber"
      : "text-sky-400";
  return {
    id: `sleep-${s.id}`,
    category: "Health",
    type: "MorningStatus",
    title: "Sleep & Recovery",
    timestamp: sleepTimestamp(s),
    highlight: lowRecovery,
    metrics: [
      {
        label: "Recovery",
        value: recovery != null ? `${Math.round(recovery)}%` : "—",
        colorClass: recoveryColor,
      },
      {
        label: "Sleep",
        value: score != null ? Math.round(score).toString() : "—",
        colorClass: scoreColor,
      },
      {
        label: "HRV",
        value: hrv != null ? `${Math.round(hrv)}ms` : "—",
      },
      {
        label: "Time",
        value:
          totalMin != null
            ? `${Math.floor(totalMin / 60)}h ${Math.round(totalMin % 60)}m`
            : "—",
        colorClass: lowRecovery ? "text-brand-amber" : undefined,
      },
    ],
    navigateTo: "/sleep",
  };
}

/** Merge raw API responses into a unified, newest-first timeline.
 *  Strength rows whose `activity_id` matches a Strava WeightTraining
 *  activity dedup with the strength row winning. Sleep rows are deduped
 *  by date (eight_sleep wins over whoop when both are present). */
export function buildHistoryEvents(
  activities: ActivitySummary[],
  sleep: SleepSession[],
  strength: StrengthSession[]
): HistoryEvent[] {
  const linkedActivityIds = new Set(
    strength.map((s) => s.activity_id).filter((x): x is number => x != null)
  );
  const sleepByDate = new Map<string, SleepSession>();
  for (const s of sleep) {
    const existing = sleepByDate.get(s.date);
    if (!existing || (s.source === "eight_sleep" && existing.source !== "eight_sleep")) {
      sleepByDate.set(s.date, s);
    }
  }
  const events: HistoryEvent[] = [];
  for (const a of activities) {
    if (linkedActivityIds.has(a.id)) continue;
    events.push(activityToEvent(a));
  }
  for (const s of strength) {
    events.push(strengthToEvent(s));
  }
  for (const s of sleepByDate.values()) {
    events.push(sleepToEvent(s));
  }
  events.sort((a, b) =>
    new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );
  return events;
}

export function applyHistoryFilter(
  events: HistoryEvent[],
  filter: FilterId
): HistoryEvent[] {
  if (filter === "All") return events;
  if (filter === "Workout") return events.filter((e) => e.category === "Workout");
  if (filter === "Health") return events.filter((e) => e.category === "Health");
  return events.filter((e) => e.type === filter);
}

/** "Today, 6:30 AM" / "Yesterday, 4:15 PM" / "Mon, Apr 24, 5:30 PM". */
export function formatRelativeDate(iso: string, today: Date = new Date()): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const ymd = (x: Date) =>
    `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  if (ymd(d) === ymd(today)) return `Today, ${time}`;
  if (ymd(d) === ymd(yesterday)) return `Yesterday, ${time}`;
  const datePart = d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  return `${datePart}, ${time}`;
}
