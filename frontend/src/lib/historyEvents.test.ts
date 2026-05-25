import { describe, expect, it } from "vitest";
import {
  applyHistoryFilter,
  buildHistoryEvents,
  classifyActivity,
  formatRelativeDate,
} from "./historyEvents";
import type { ActivitySummary } from "../api/activities";
import type { SleepSession } from "../api/sleep";
import type { StrengthSession } from "../api/strength";

function makeActivity(over: Partial<ActivitySummary> = {}): ActivitySummary {
  return {
    id: 1,
    strava_id: 1001,
    name: "Test Activity",
    sport_type: "Run",
    start_date: "2026-04-25T10:00:00Z",
    start_date_local: "2026-04-25T10:00:00",
    elapsed_time: 1800,
    moving_time: 1800,
    distance: 5000,
    total_elevation: 30,
    average_hr: 150,
    max_hr: 170,
    average_speed: 3.0,
    max_speed: 4.0,
    average_power: null,
    max_power: null,
    weighted_avg_power: null,
    average_cadence: null,
    calories: null,
    kilojoules: null,
    suffer_score: 50,
    device_watts: null,
    workout_type: null,
    available_zones: null,
    enrichment_status: "complete",
    enriched_at: null,
    classification_type: "easy",
    classification_flags: null,
    classified_at: null,
    weather_enriched: false,
    elev_high_m: null,
    elev_low_m: null,
    base_elevation_m: null,
    elevation_enriched: false,
    location_id: null,
    start_lat: null,
    start_lng: null,
    rpe: null,
    user_notes: null,
    rated_at: null,
    ...over,
  };
}

function makeSleep(over: Partial<SleepSession> = {}): SleepSession {
  return {
    id: 10,
    source: "eight_sleep",
    date: "2026-04-25",
    bed_time: "2026-04-24T23:00:00",
    wake_time: "2026-04-25T07:00:00",
    total_duration: 480,
    deep_sleep: 90,
    rem_sleep: 110,
    light_sleep: 270,
    awake_time: 10,
    sleep_score: 80,
    sleep_fitness_score: 75,
    avg_hr: 56,
    hrv: 60,
    respiratory_rate: 14,
    bed_temp: null,
    tnt_count: 5,
    latency: 600,
    ...over,
  };
}

function makeStrength(over: Partial<StrengthSession> = {}): StrengthSession {
  return {
    date: "2026-04-25",
    exercise_count: 4,
    total_sets: 14,
    total_volume_kg: 6000,
    activity_id: null,
    ...over,
  };
}

describe("classifyActivity", () => {
  it("maps known Strava CamelCase sport types", () => {
    expect(classifyActivity("Ride")).toBe("Ride");
    expect(classifyActivity("EBikeRide")).toBe("Ride");
    expect(classifyActivity("Run")).toBe("Run");
    expect(classifyActivity("TrailRun")).toBe("Run");
    expect(classifyActivity("WeightTraining")).toBe("Strength");
    expect(classifyActivity("Hike")).toBe("Hike");
    expect(classifyActivity("Walk")).toBe("Walk");
    expect(classifyActivity("Yoga")).toBe("Other");
    expect(classifyActivity(null)).toBe("Other");
  });

  it("maps Apple Health normalized lowercase sport types", () => {
    // These are the normalized values emitted by the backend's
    // sport_mapping layer for Apple-only workouts.
    expect(classifyActivity("run")).toBe("Run");
    expect(classifyActivity("ride")).toBe("Ride");
    expect(classifyActivity("walk")).toBe("Walk");
    expect(classifyActivity("hike")).toBe("Hike");
    expect(classifyActivity("strength")).toBe("Strength");
  });

  it("falls back to Other for normalized types without a dedicated icon", () => {
    expect(classifyActivity("swim")).toBe("Other");
    expect(classifyActivity("yoga")).toBe("Other");
    expect(classifyActivity("hiit")).toBe("Other");
    expect(classifyActivity("elliptical")).toBe("Other");
    expect(classifyActivity("row")).toBe("Other");
  });
});

describe("activityToEvent (via buildHistoryEvents)", () => {
  it("renders Apple-only run with Distance/Pace metrics", () => {
    const events = buildHistoryEvents(
      [
        makeActivity({
          id: 7,
          sport_type: "run",
          source: "apple_health",
          name: "Morning Run",
        }),
      ],
      [],
      []
    );
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("Run");
    const labels = events[0].metrics.map((m) => m.label);
    expect(labels).toContain("Distance");
    expect(labels).toContain("Pace");
    expect(labels).toContain("Time");
  });

  it("renders Apple-only ride with Distance/TSS metrics", () => {
    const events = buildHistoryEvents(
      [
        makeActivity({
          id: 8,
          sport_type: "ride",
          source: "apple_health",
          name: "Bike Commute",
        }),
      ],
      [],
      []
    );
    expect(events[0].type).toBe("Ride");
    const labels = events[0].metrics.map((m) => m.label);
    expect(labels).toContain("Distance");
    expect(labels).toContain("TSS");
  });

  it("renders Apple-only strength as Strength type", () => {
    const events = buildHistoryEvents(
      [
        makeActivity({
          id: 9,
          sport_type: "strength",
          source: "apple_health",
          name: "Strength",
        }),
      ],
      [],
      []
    );
    expect(events[0].type).toBe("Strength");
  });

  it("routes Apple-only workouts to /activities/:id with ?source=apple_health (using the HDP id)", () => {
    // Regression for docs/bugs/apple-watch-routing-collision.md: when an
    // Apple Watch workout's HDP id collides with a Strava activity id, the
    // bare URL would resolve the Strava row on the backend. The query
    // string disambiguates the source so the right detail row is returned.
    const events = buildHistoryEvents(
      [
        makeActivity({
          id: 5,
          sport_type: "run",
          source: "apple_health",
          name: "Apple Run",
        }),
      ],
      [],
      []
    );
    expect(events[0].navigateTo).toBe("/activities/5?source=apple_health");
  });

  it("appends ?source=strava for Strava-sourced workouts", () => {
    const events = buildHistoryEvents(
      [
        makeActivity({
          id: 11,
          sport_type: "Run",
          source: "strava",
          name: "Strava Run",
        }),
      ],
      [],
      []
    );
    expect(events[0].navigateTo).toBe("/activities/11?source=strava");
  });

  it("keeps navigateTo unqualified for legacy rows with no source set", () => {
    const events = buildHistoryEvents(
      [
        makeActivity({
          id: 12,
          sport_type: "Run",
          source: null,
          name: "Legacy Run",
        }),
      ],
      [],
      []
    );
    expect(events[0].navigateTo).toBe("/activities/12");
  });
});

describe("buildHistoryEvents", () => {
  it("merges and sorts newest-first", () => {
    const events = buildHistoryEvents(
      [
        makeActivity({
          id: 1,
          source: "strava",
          start_date_local: "2026-04-23T10:00:00",
        }),
        makeActivity({
          id: 2,
          source: "strava",
          start_date_local: "2026-04-25T10:00:00",
        }),
      ],
      [makeSleep({ id: 1, date: "2026-04-24", wake_time: "2026-04-24T07:00:00" })],
      [makeStrength({ date: "2026-04-22" })]
    );
    expect(events.map((e) => e.id)).toEqual([
      "strava-2",
      "sleep-1",
      "strava-1",
      "strength-2026-04-22",
    ]);
  });

  it("uses source-prefixed keys so an Apple workout and Strava activity with the same numeric id do not collide", () => {
    // Regression for review-round-1: prior to this fix both events keyed as
    // "activity-1" and React warned about duplicate child keys.
    // Also regression for docs/bugs/apple-watch-routing-collision.md: the
    // two rows must navigate to distinct URLs (disambiguated by ?source=)
    // so the detail page resolves the right row on the backend.
    const events = buildHistoryEvents(
      [
        makeActivity({
          id: 1,
          source: "strava",
          name: "Strava Activity",
          start_date_local: "2026-04-25T10:00:00",
        }),
        makeActivity({
          id: 1,
          source: "apple_health",
          name: "Apple Workout",
          start_date_local: "2026-04-25T11:00:00",
        }),
      ],
      [],
      []
    );
    const ids = events.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(expect.arrayContaining(["apple-1", "strava-1"]));

    const apple = events.find((e) => e.id === "apple-1");
    const strava = events.find((e) => e.id === "strava-1");
    expect(apple).toBeDefined();
    expect(strava).toBeDefined();
    expect(apple!.navigateTo).not.toBe(strava!.navigateTo);
    expect(apple!.navigateTo).toContain("source=apple_health");
    expect(strava!.navigateTo).toContain("source=strava");
  });

  it("falls back to an 'activity-' prefix for legacy rows missing a source", () => {
    const events = buildHistoryEvents(
      [makeActivity({ id: 5, source: null, name: "Legacy" })],
      [],
      []
    );
    expect(events[0].id).toBe("activity-5");
  });

  it("dedups a strength session that points to a Strava WeightTraining activity", () => {
    const events = buildHistoryEvents(
      [
        makeActivity({
          id: 99,
          sport_type: "WeightTraining",
          name: "Lift",
          start_date_local: "2026-04-25T18:00:00",
        }),
      ],
      [],
      [makeStrength({ date: "2026-04-25", activity_id: 99 })]
    );
    expect(events).toHaveLength(1);
    expect(events[0].id).toBe("strength-2026-04-25");
  });

  it("flags low-recovery nights with highlight + amber", () => {
    const events = buildHistoryEvents(
      [],
      [makeSleep({ id: 1, sleep_fitness_score: 42, sleep_score: 55, hrv: 38 })],
      []
    );
    expect(events[0].highlight).toBe(true);
    const recovery = events[0].metrics.find((m) => m.label === "Recovery");
    expect(recovery?.colorClass).toBe("text-brand-amber");
    expect(recovery?.value).toBe("42%");
  });

  it("does not flag healthy nights", () => {
    const events = buildHistoryEvents(
      [],
      [makeSleep({ id: 1, sleep_fitness_score: 78 })],
      []
    );
    expect(events[0].highlight).toBeFalsy();
  });

  it("routes strength rows with no linked activity to /workouts/lifting/:date", () => {
    const events = buildHistoryEvents(
      [],
      [],
      [makeStrength({ date: "2026-04-25", activity_id: null })]
    );
    expect(events[0].navigateTo).toBe("/workouts/lifting/2026-04-25");
  });

  it("routes strength rows with linked activity to /workouts/lifting/:date", () => {
    // The detail page surfaces the linked device workout as its own chip,
    // so we always navigate to the date-keyed lifting page regardless of
    // whether `activity_id` is set.
    const events = buildHistoryEvents(
      [],
      [],
      [makeStrength({ date: "2026-04-25", activity_id: 42 })]
    );
    expect(events[0].navigateTo).toBe("/workouts/lifting/2026-04-25");
  });

  it("flags strength events as HR-linked when hr_linked is true", () => {
    const events = buildHistoryEvents(
      [],
      [],
      [makeStrength({ activity_id: 42, hr_linked: true })]
    );
    expect(events[0].hrLinked).toBe(true);
  });

  it("defaults hrLinked to false when the strength row has no hr_linked flag", () => {
    const events = buildHistoryEvents(
      [],
      [],
      [makeStrength({ activity_id: null })]
    );
    expect(events[0].hrLinked).toBe(false);
  });

  it("dedupes sleep rows by date, preferring eight_sleep over whoop", () => {
    const events = buildHistoryEvents(
      [],
      [
        makeSleep({ id: 100, source: "whoop", date: "2026-04-25" }),
        makeSleep({ id: 101, source: "eight_sleep", date: "2026-04-25" }),
        makeSleep({ id: 102, source: "whoop", date: "2026-04-24" }),
      ],
      []
    );
    expect(events.map((e) => e.id).sort()).toEqual(["sleep-101", "sleep-102"]);
  });

  it("uses unique sleep keys so multiple-source data does not collide", () => {
    const events = buildHistoryEvents(
      [],
      [
        makeSleep({ id: 1, source: "eight_sleep", date: "2026-04-25" }),
        makeSleep({ id: 2, source: "whoop", date: "2026-04-26" }),
      ],
      []
    );
    const ids = events.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("encodes the row's date in navigateTo so /sleep deep-links scope correctly", () => {
    // Regression for issue #51: without ?date=, /sleep always falls back to
    // the latest Eight Sleep row. See docs/bugs/sleep-detail-date-scope.md.
    const events = buildHistoryEvents(
      [],
      [makeSleep({ id: 77, date: "2025-05-12" })],
      []
    );
    expect(events).toHaveLength(1);
    expect(events[0].navigateTo).toBe("/sleep?date=2025-05-12");
  });
});

describe("applyHistoryFilter", () => {
  const events = buildHistoryEvents(
    [
      makeActivity({ id: 1, sport_type: "Ride", name: "Ride" }),
      makeActivity({ id: 2, sport_type: "Run", name: "Run" }),
    ],
    [makeSleep({ id: 1 })],
    [makeStrength()]
  );

  it("All returns everything", () => {
    expect(applyHistoryFilter(events, "All")).toHaveLength(events.length);
  });
  it("Workout returns activities + strength", () => {
    const got = applyHistoryFilter(events, "Workout");
    expect(got.every((e) => e.category === "Workout")).toBe(true);
    expect(got).toHaveLength(3);
  });
  it("Health returns sleep only", () => {
    const got = applyHistoryFilter(events, "Health");
    expect(got).toHaveLength(1);
    expect(got[0].type).toBe("MorningStatus");
  });
  it("Ride returns rides only", () => {
    const got = applyHistoryFilter(events, "Ride");
    expect(got).toHaveLength(1);
    expect(got[0].type).toBe("Ride");
  });
  it("Strength returns strength only", () => {
    const got = applyHistoryFilter(events, "Strength");
    expect(got).toHaveLength(1);
    expect(got[0].type).toBe("Strength");
  });
});

describe("formatRelativeDate", () => {
  const today = new Date("2026-04-25T12:00:00");
  it('renders "Today" for the same calendar day', () => {
    expect(formatRelativeDate("2026-04-25T08:30:00", today)).toMatch(/^Today,/);
  });
  it('renders "Yesterday" for the prior day', () => {
    expect(formatRelativeDate("2026-04-24T18:15:00", today)).toMatch(/^Yesterday,/);
  });
  it("renders weekday for older dates", () => {
    const out = formatRelativeDate("2026-04-20T17:30:00", today);
    expect(out).not.toMatch(/^Today/);
    expect(out).not.toMatch(/^Yesterday/);
    expect(out).toContain("Apr 20");
  });
});
