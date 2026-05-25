// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  collapseSleepSessionsToNights,
  useActivityNeighbors,
  useLiftingNeighbors,
  useSleepNeighbors,
} from "./useDetailNeighbors";
import type { SleepSession } from "../api/sleep";
import type { ActivitySummary } from "../api/activities";
import type { StrengthSession } from "../api/strength";

vi.mock("../api/sleep", () => ({
  fetchSleepSessions: vi.fn(),
}));
vi.mock("../api/activities", () => ({
  fetchActivities: vi.fn(),
}));
vi.mock("../api/strength", () => ({
  fetchStrengthSessions: vi.fn(),
}));

import { fetchSleepSessions } from "../api/sleep";
import { fetchActivities } from "../api/activities";
import { fetchStrengthSessions } from "../api/strength";

const mockedFetchSleep = vi.mocked(fetchSleepSessions);
const mockedFetchActivities = vi.mocked(fetchActivities);
const mockedFetchStrength = vi.mocked(fetchStrengthSessions);

function withQuery() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
      },
    },
  });
  return {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}

// ── Test factories ──────────────────────────────────────────────────────────

function mkSleep(
  date: string,
  source: "whoop" | "eight_sleep",
  id: number,
): SleepSession {
  return {
    id,
    source,
    external_id: `${source}-${id}`,
    date,
    bed_time: null,
    wake_time: null,
    total_duration: 420,
    deep_sleep: 80,
    rem_sleep: 100,
    light_sleep: 220,
    awake_time: 20,
    sleep_score: 80,
    sleep_fitness_score: null,
    avg_hr: 54,
    hrv: 60,
    respiratory_rate: 14,
    bed_temp: null,
    tnt_count: null,
    latency: null,
  };
}

function mkActivity(
  id: number,
  start_date_local: string,
  source: ActivitySummary["source"] = "strava",
): ActivitySummary {
  return {
    id,
    strava_id: id,
    name: `Activity ${id}`,
    sport_type: "Run",
    source,
    external_id: null,
    superseded_by_id: null,
    start_date: start_date_local,
    start_date_local,
    elapsed_time: 1800,
    moving_time: 1800,
    distance: 5000,
    total_elevation: 0,
    average_hr: 140,
    max_hr: 160,
    average_speed: 3.0,
    max_speed: 4.0,
    average_power: null,
    max_power: null,
    weighted_avg_power: null,
    average_cadence: null,
    calories: 400,
    kilojoules: null,
    suffer_score: null,
    device_watts: null,
    workout_type: null,
    available_zones: null,
    enrichment_status: "complete",
    enriched_at: null,
    classification_type: null,
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
  };
}

function mkLift(date: string): StrengthSession {
  return {
    date,
    exercise_count: 3,
    total_sets: 9,
    total_volume_kg: 1000,
    activity_id: null,
  };
}

// ── collapseSleepSessionsToNights ───────────────────────────────────────────

describe("collapseSleepSessionsToNights", () => {
  it("returns [] for an empty list", () => {
    expect(collapseSleepSessionsToNights([])).toEqual([]);
  });

  it("collapses two-source rows that share a date into one canonical night", () => {
    const sessions = [
      mkSleep("2026-05-22", "whoop", 1),
      mkSleep("2026-05-22", "eight_sleep", 2),
      mkSleep("2026-05-21", "whoop", 3),
      mkSleep("2026-05-21", "eight_sleep", 4),
    ];
    expect(collapseSleepSessionsToNights(sessions)).toEqual([
      "2026-05-22",
      "2026-05-21",
    ]);
  });

  it("collapses two-source rows that label the same night off-by-one (±1 day)", () => {
    // WHOOP and Eight Sleep label the same physical night with adjacent
    // calendar dates — the canonical list should still emit one night.
    const sessions = [
      mkSleep("2026-05-22", "whoop", 1),
      mkSleep("2026-05-21", "eight_sleep", 2), // pairs with WHOOP 05-22
      mkSleep("2026-05-19", "whoop", 3),
      mkSleep("2026-05-18", "eight_sleep", 4), // pairs with WHOOP 05-19
    ];
    expect(collapseSleepSessionsToNights(sessions)).toEqual([
      "2026-05-22",
      "2026-05-19",
    ]);
  });

  it("keeps unrelated nights separate when the gap exceeds the pairing window", () => {
    const sessions = [
      mkSleep("2026-05-22", "whoop", 1),
      mkSleep("2026-05-20", "eight_sleep", 2), // 2-day gap → separate night
    ];
    expect(collapseSleepSessionsToNights(sessions)).toEqual([
      "2026-05-22",
      "2026-05-20",
    ]);
  });
});

// ── useSleepNeighbors ──────────────────────────────────────────────────────

describe("useSleepNeighbors", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("treats latest as current when currentDate is undefined; next disabled, prev = second-newest", async () => {
    mockedFetchSleep.mockResolvedValueOnce([
      mkSleep("2026-05-22", "whoop", 1),
      mkSleep("2026-05-21", "whoop", 2),
      mkSleep("2026-05-19", "whoop", 3),
    ]);

    const { wrapper } = withQuery();
    const { result } = renderHook(() => useSleepNeighbors(undefined), {
      wrapper,
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.nextDate).toBeNull();
    expect(result.current.prevDate).toBe("2026-05-21");
  });

  it("returns both neighbors when current is in the middle of the list", async () => {
    mockedFetchSleep.mockResolvedValueOnce([
      mkSleep("2026-05-22", "whoop", 1),
      mkSleep("2026-05-21", "whoop", 2),
      mkSleep("2026-05-19", "whoop", 3),
    ]);

    const { wrapper } = withQuery();
    const { result } = renderHook(() => useSleepNeighbors("2026-05-21"), {
      wrapper,
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.nextDate).toBe("2026-05-22");
    expect(result.current.prevDate).toBe("2026-05-19");
  });

  it("returns null prev when current is the oldest known night", async () => {
    mockedFetchSleep.mockResolvedValueOnce([
      mkSleep("2026-05-22", "whoop", 1),
      mkSleep("2026-05-19", "whoop", 2),
    ]);

    const { wrapper } = withQuery();
    const { result } = renderHook(() => useSleepNeighbors("2026-05-19"), {
      wrapper,
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.prevDate).toBeNull();
    expect(result.current.nextDate).toBe("2026-05-22");
  });

  it("returns null neighbors when no sessions exist", async () => {
    mockedFetchSleep.mockResolvedValueOnce([]);

    const { wrapper } = withQuery();
    const { result } = renderHook(() => useSleepNeighbors(undefined), {
      wrapper,
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.prevDate).toBeNull();
    expect(result.current.nextDate).toBeNull();
  });

  it("collapses two-source rows when computing neighbors", async () => {
    // Same physical nights labelled off-by-one across providers.
    mockedFetchSleep.mockResolvedValueOnce([
      mkSleep("2026-05-22", "whoop", 1),
      mkSleep("2026-05-21", "eight_sleep", 2), // same night as 05-22
      mkSleep("2026-05-19", "whoop", 3),
      mkSleep("2026-05-18", "eight_sleep", 4), // same night as 05-19
    ]);

    const { wrapper } = withQuery();
    const { result } = renderHook(() => useSleepNeighbors("2026-05-22"), {
      wrapper,
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    // Two canonical nights — 05-22 and 05-19. Currently on 05-22 → next null,
    // prev jumps to 05-19 (NOT 05-21, which was folded into the 05-22 night).
    expect(result.current.nextDate).toBeNull();
    expect(result.current.prevDate).toBe("2026-05-19");
  });
});

// ── useActivityNeighbors ───────────────────────────────────────────────────

describe("useActivityNeighbors", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("returns null both ways when activity list is empty", async () => {
    mockedFetchActivities.mockResolvedValueOnce([]);
    const { wrapper } = withQuery();
    const { result } = renderHook(() => useActivityNeighbors(7, "strava"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.prev).toBeNull();
    expect(result.current.next).toBeNull();
  });

  it("returns both neighbors when current is in the middle", async () => {
    mockedFetchActivities.mockResolvedValueOnce([
      mkActivity(1, "2026-05-22T10:00:00"),
      mkActivity(2, "2026-05-21T10:00:00"),
      mkActivity(3, "2026-05-20T10:00:00"),
    ]);
    const { wrapper } = withQuery();
    const { result } = renderHook(() => useActivityNeighbors(2, "strava"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.next).toEqual({ id: 1, source: "strava" });
    expect(result.current.prev).toEqual({ id: 3, source: "strava" });
  });

  it("returns null next at the newest activity", async () => {
    mockedFetchActivities.mockResolvedValueOnce([
      mkActivity(1, "2026-05-22T10:00:00"),
      mkActivity(2, "2026-05-21T10:00:00"),
    ]);
    const { wrapper } = withQuery();
    const { result } = renderHook(() => useActivityNeighbors(1, "strava"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.next).toBeNull();
    expect(result.current.prev).toEqual({ id: 2, source: "strava" });
  });

  it("returns null prev at the oldest activity", async () => {
    mockedFetchActivities.mockResolvedValueOnce([
      mkActivity(1, "2026-05-22T10:00:00"),
      mkActivity(2, "2026-05-21T10:00:00"),
    ]);
    const { wrapper } = withQuery();
    const { result } = renderHook(() => useActivityNeighbors(2, "strava"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.next).toEqual({ id: 1, source: "strava" });
    expect(result.current.prev).toBeNull();
  });

  it("disambiguates Apple vs Strava activities that share an id", async () => {
    // Same id, different source rows interleaved chronologically.
    mockedFetchActivities.mockResolvedValueOnce([
      mkActivity(5, "2026-05-22T10:00:00", "strava"),
      mkActivity(5, "2026-05-21T10:00:00", "apple_health"),
      mkActivity(6, "2026-05-20T10:00:00", "strava"),
    ]);
    const { wrapper } = withQuery();
    const { result } = renderHook(
      () => useActivityNeighbors(5, "apple_health"),
      { wrapper },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    // Apple row at 05-21: next = Strava 5 (05-22), prev = Strava 6 (05-20).
    expect(result.current.next).toEqual({ id: 5, source: "strava" });
    expect(result.current.prev).toEqual({ id: 6, source: "strava" });
  });

  it("returns null neighbors when current row is not in the list", async () => {
    mockedFetchActivities.mockResolvedValueOnce([
      mkActivity(1, "2026-05-22T10:00:00"),
      mkActivity(2, "2026-05-21T10:00:00"),
    ]);
    const { wrapper } = withQuery();
    const { result } = renderHook(
      () => useActivityNeighbors(999, "strava"),
      { wrapper },
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.prev).toBeNull();
    expect(result.current.next).toBeNull();
  });
});

// ── useLiftingNeighbors ────────────────────────────────────────────────────

describe("useLiftingNeighbors", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("returns null both ways when there are no lifting sessions", async () => {
    mockedFetchStrength.mockResolvedValueOnce([]);
    const { wrapper } = withQuery();
    const { result } = renderHook(() => useLiftingNeighbors("2026-05-22"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.prevDate).toBeNull();
    expect(result.current.nextDate).toBeNull();
  });

  it("returns both neighbors in the middle", async () => {
    mockedFetchStrength.mockResolvedValueOnce([
      mkLift("2026-05-22"),
      mkLift("2026-05-20"),
      mkLift("2026-05-18"),
    ]);
    const { wrapper } = withQuery();
    const { result } = renderHook(() => useLiftingNeighbors("2026-05-20"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.nextDate).toBe("2026-05-22");
    expect(result.current.prevDate).toBe("2026-05-18");
  });

  it("returns null next at the newest session", async () => {
    mockedFetchStrength.mockResolvedValueOnce([
      mkLift("2026-05-22"),
      mkLift("2026-05-20"),
    ]);
    const { wrapper } = withQuery();
    const { result } = renderHook(() => useLiftingNeighbors("2026-05-22"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.nextDate).toBeNull();
    expect(result.current.prevDate).toBe("2026-05-20");
  });

  it("returns null prev at the oldest session", async () => {
    mockedFetchStrength.mockResolvedValueOnce([
      mkLift("2026-05-22"),
      mkLift("2026-05-20"),
    ]);
    const { wrapper } = withQuery();
    const { result } = renderHook(() => useLiftingNeighbors("2026-05-20"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.nextDate).toBe("2026-05-22");
    expect(result.current.prevDate).toBeNull();
  });

  it("returns null neighbors when the current date is not in the list", async () => {
    mockedFetchStrength.mockResolvedValueOnce([
      mkLift("2026-05-22"),
      mkLift("2026-05-20"),
    ]);
    const { wrapper } = withQuery();
    const { result } = renderHook(() => useLiftingNeighbors("2024-01-01"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.prevDate).toBeNull();
    expect(result.current.nextDate).toBeNull();
  });
});
