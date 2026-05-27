import type { ReactNode } from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "../test/renderWithQuery";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mutable param so tests can simulate navigation between two activity ids.
const routeParams: { id: string } = { id: "7" };
function setRouteId(id: string | number) {
  routeParams.id = String(id);
}

// Mutable query string so tests can simulate a `?source=...` query without
// pulling in a full MemoryRouter — `useSearchParams` is mocked to return a
// `URLSearchParams` view onto this value.
let routeSearch = "";
function setRouteSearch(search: string) {
  routeSearch = search;
}

const { mockNavigate } = vi.hoisted(() => ({ mockNavigate: vi.fn() }));

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: routeParams.id }),
  useNavigate: () => mockNavigate,
  useSearchParams: () => {
    const params = new URLSearchParams(routeSearch);
    const setParams = vi.fn();
    return [params, setParams] as const;
  },
}));

vi.mock("recharts", () => {
  const passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: passthrough,
    ComposedChart: ({ children }: { children?: ReactNode }) => (
      <div data-testid="composed-chart">{children}</div>
    ),
    LineChart: passthrough,
    Line: () => <div />,
    Area: () => <div />,
    Bar: () => <div />,
    BarChart: passthrough,
    XAxis: () => <div />,
    YAxis: () => <div />,
    CartesianGrid: () => <div />,
    Tooltip: () => <div />,
    Legend: () => <div />,
  };
});

vi.mock("../api/activities", () => ({
  fetchActivity: vi.fn(),
  fetchActivities: vi.fn(() => Promise.resolve([])),
  fetchActivityStreams: vi.fn(),
  reclassifyActivity: vi.fn(),
  patchActivityShoe: vi.fn(),
}));

vi.mock("../api/insights", () => ({
  fetchLatestWorkoutInsight: vi.fn(),
}));

vi.mock("../api/weather", () => ({
  getActivityWeather: vi.fn(),
}));

vi.mock("../api/strength", () => ({
  fetchStrengthSessionOptional: vi.fn().mockResolvedValue(null),
}));

vi.mock("../hooks/useUnits", () => ({
  useUnits: () => ({ units: "imperial" }),
  formatTemperature: (c: number | null | undefined) =>
    c == null ? "—" : `${Math.round(c)}°`,
  formatWindSpeed: () => "8 mph",
  formatElevation: (meters: number | null | undefined) =>
    meters == null ? "—" : `${Math.round(meters)} m`,
}));

vi.mock("./ClassificationBadge", () => ({
  default: () => <div>Classification badge</div>,
}));

vi.mock("./LocationPicker", () => ({
  default: () => <div>Location picker</div>,
}));

vi.mock("./RPECard", () => ({
  default: () => <div>RPE card</div>,
}));

vi.mock("./shoes/ShoeSelector", () => ({
  default: () => <div>Shoe selector</div>,
}));

vi.mock("./WeatherCard", () => ({
  default: () => <div>Weather card expanded</div>,
}));

import ActivityDetailPage from "./ActivityDetail";
import {
  type ActivityDetail as ActivityDetailResponse,
  type ActivitySummary,
  fetchActivities,
  fetchActivity,
  fetchActivityStreams,
} from "../api/activities";
import { fetchLatestWorkoutInsight } from "../api/insights";
import { getActivityWeather } from "../api/weather";

const mockedFetchActivity = vi.mocked(fetchActivity);
const mockedFetchActivities = vi.mocked(fetchActivities);
const mockedFetchActivityStreams = vi.mocked(fetchActivityStreams);
const mockedFetchLatestWorkoutInsight = vi.mocked(fetchLatestWorkoutInsight);
const mockedGetActivityWeather = vi.mocked(getActivityWeather);

function makeActivity(
  overrides: Partial<ActivityDetailResponse> = {}
): ActivityDetailResponse {
  return {
    id: 7,
    strava_id: 77,
    name: "Evening Run",
    sport_type: "Run",
    start_date: "2026-04-20T22:00:00",
    start_date_local: "2026-04-20T18:00:00",
    elapsed_time: 1800,
    moving_time: 1800,
    distance: 5000,
    total_elevation: 50,
    average_hr: 150,
    max_hr: 170,
    average_speed: 3.3,
    max_speed: 4.5,
    average_power: null,
    max_power: null,
    weighted_avg_power: null,
    average_cadence: null,
    calories: 400,
    kilojoules: null,
    suffer_score: 50,
    device_watts: null,
    workout_type: null,
    available_zones: null,
    enrichment_status: "complete",
    enriched_at: "2026-04-20T22:05:00",
    classification_type: "easy",
    classification_flags: [],
    classified_at: "2026-04-20T22:06:00",
    weather_enriched: false,
    elev_high_m: null,
    elev_low_m: null,
    base_elevation_m: null,
    elevation_enriched: false,
    location_id: null,
    start_lat: 40.0,
    start_lng: -105.2,
    rpe: null,
    user_notes: null,
    rated_at: null,
    shoe_id: null,
    laps: [],
    zones: null,
    weather: null,
    streams_cached: false,
    hr_drift: null,
    pace_hr_decoupling: null,
    power_hr_decoupling: null,
    raw_data: null,
    ...overrides,
  };
}

describe("ActivityDetailPage", () => {
  beforeEach(() => {
    setRouteId(7);
    setRouteSearch("");
    mockedGetActivityWeather.mockResolvedValue(null);
    // Default the activities list (used by the prev/next arrow neighbors hook)
    // to empty so existing assertions aren't affected. Individual tests
    // override when exercising arrow navigation.
    mockedFetchActivities.mockResolvedValue([]);
    mockNavigate.mockClear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loads insight and streams on demand for a Run", async () => {
    mockedFetchActivity.mockResolvedValue(makeActivity());
    mockedFetchLatestWorkoutInsight.mockResolvedValue({
      activity_id: 7,
      workout: {
        id: 7,
        strava_id: 77,
        source: "strava",
        name: "Evening Run",
        sport_type: "Run",
        classification_type: "easy",
        classification_flags: [],
        start_date: "2026-04-20T22:00:00",
        start_date_local: "2026-04-20T18:00:00",
        distance_m: 5000,
        moving_time_s: 1800,
        elapsed_time_s: 1800,
        total_elevation_m: 50,
        avg_hr: 150,
        max_hr: 170,
        avg_speed_ms: 3.3,
        pace: "5:03/km",
        avg_power_w: null,
        weighted_avg_power_w: null,
        kilojoules: null,
        suffer_score: 50,
        calories: 400,
        laps: [],
        hr_zones: null,
        hr_drift: null,
        pace_hr_decoupling: null,
        power_hr_decoupling: null,
        weather: null,
        pre_workout_sleep: null,
        historical_comparison: null,
      },
      insight: {
        headline: "Strong aerobic work",
        takeaway: "You kept the effort controlled throughout.",
        notable_segments: [
          { label: "Middle 2 km", detail: "Best rhythm of the run." },
        ],
        vs_history: "A touch smoother than your recent easy runs.",
        flags: ["steady pacing"],
      },
      model: "gpt-4o",
      generated_at: "2026-04-23T20:00:00Z",
      cached: false,
    });
    mockedFetchActivityStreams.mockResolvedValue({
      time: [0, 60, 120],
      heartrate: [140, 145, 148],
      velocity_smooth: [3.2, 3.3, 3.4],
    });

    renderWithQuery(<ActivityDetailPage />);

    await screen.findByText("Evening Run");

    fireEvent.click(
      screen.getByRole("button", { name: "Analyze This Workout" })
    );
    await screen.findByText("Strong aerobic work");
    expect(mockedFetchLatestWorkoutInsight).toHaveBeenCalledWith({
      activityId: 7,
    });
    expect(screen.getByText("Model: gpt-4o")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load Streams" }));
    await waitFor(() =>
      expect(mockedFetchActivityStreams).toHaveBeenCalledWith(7, null)
    );
    expect(screen.getByTestId("composed-chart")).toBeInTheDocument();
  });

  it("surfaces lazy insight and stream errors", async () => {
    mockedFetchActivity.mockResolvedValue(makeActivity());
    mockedFetchLatestWorkoutInsight.mockRejectedValue(
      new Error("Insight unavailable")
    );
    mockedFetchActivityStreams.mockRejectedValue(
      new Error("Streams unavailable")
    );

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Evening Run");

    fireEvent.click(
      screen.getByRole("button", { name: "Analyze This Workout" })
    );
    await screen.findByText("Insight unavailable");

    fireEvent.click(screen.getByRole("button", { name: "Load Streams" }));
    await screen.findByText("Streams unavailable");
  });

  it("renders Ride layout with Power and Speed cells for a ride", async () => {
    mockedFetchActivity.mockResolvedValue(
      makeActivity({
        name: "Morning Tempo Ride",
        sport_type: "Ride",
        average_power: 185,
        weighted_avg_power: 210,
        average_cadence: 88,
      })
    );

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Morning Tempo Ride");
    expect(screen.getByText("Power (Avg/NP)")).toBeInTheDocument();
    expect(screen.getByText("Avg Speed")).toBeInTheDocument();
  });

  it("renders a power zone card when a ride has no HR zones", async () => {
    mockedFetchActivity.mockResolvedValue(
      makeActivity({
        name: "Power Zone Ride",
        sport_type: "Ride",
        zones: [
          {
            type: "power",
            distribution_buckets: [
              { min: 0, max: 120, time: 300 },
              { min: 121, max: 180, time: 600 },
            ],
          },
        ],
      })
    );

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Power Zone Ride");
    expect(screen.getByText("Time in Power Zones")).toBeInTheDocument();
  });

  it("keeps sub-mile split distances labeled in meters", async () => {
    mockedFetchActivity.mockResolvedValue(
      makeActivity({
        laps: [
          {
            lap_index: 1,
            name: null,
            elapsed_time: 90,
            moving_time: 90,
            distance: 400,
            start_date: null,
            average_speed: 4,
            max_speed: null,
            average_heartrate: 140,
            max_heartrate: 150,
            average_cadence: null,
            average_watts: null,
            total_elevation_gain: 0,
            pace_zone: null,
            hr_zone: null,
            split: null,
            start_index: null,
            end_index: null,
          },
        ],
      })
    );

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Evening Run");
    expect(screen.getByText("400 m")).toBeInTheDocument();
  });

  it("renders Strength layout (no Distance, no Splits) for a WeightTraining activity", async () => {
    mockedFetchActivity.mockResolvedValue(
      makeActivity({
        name: "Lower Body Power",
        sport_type: "WeightTraining",
        distance: null,
      })
    );

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Lower Body Power");
    // Strength variant never shows Avg Pace or Avg Speed.
    expect(screen.queryByText("Avg Pace")).not.toBeInTheDocument();
    expect(screen.queryByText("Avg Speed")).not.toBeInTheDocument();
    // ...nor a Splits header.
    expect(screen.queryByText("Splits")).not.toBeInTheDocument();
  });

  it("falls back to the Run layout for Hike", async () => {
    mockedFetchActivity.mockResolvedValue(
      makeActivity({ name: "Sunrise Hike", sport_type: "Hike" })
    );

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Sunrise Hike");
    // Run layout shows Avg Pace; Ride/Strength do not.
    expect(screen.getByText("Avg Pace")).toBeInTheDocument();
  });

  it("renders the shoe selector for foot sports (Run, Hike, Walk)", async () => {
    for (const sport of ["Run", "Hike", "Walk"] as const) {
      mockedFetchActivity.mockResolvedValueOnce(
        makeActivity({ name: `Detail ${sport}`, sport_type: sport })
      );
      const { unmount } = renderWithQuery(<ActivityDetailPage />);
      await screen.findByText(`Detail ${sport}`);
      expect(screen.getByText("Shoe selector")).toBeInTheDocument();
      unmount();
    }
  });

  it("omits the shoe selector for Strength and Ride", async () => {
    for (const sport of ["WeightTraining", "Ride"] as const) {
      mockedFetchActivity.mockResolvedValueOnce(
        makeActivity({
          name: `Detail ${sport}`,
          sport_type: sport,
          distance: sport === "WeightTraining" ? null : 5000,
        })
      );
      const { unmount } = renderWithQuery(<ActivityDetailPage />);
      await screen.findByText(`Detail ${sport}`);
      expect(screen.queryByText("Shoe selector")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("hides RPE, LocationPicker, and Insight panels for Apple Health workouts", async () => {
    mockedFetchActivity.mockResolvedValue(
      makeActivity({
        name: "Apple Run",
        sport_type: "Run",
        source: "apple_health",
        start_lat: null,
        start_lng: null,
      })
    );
    // Apple streams are auto-fetched on mount; resolve to an empty object so
    // the chart degrades gracefully and we don't trip the unhandled promise.
    mockedFetchActivityStreams.mockResolvedValue({});

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Apple Run");

    // RPE / LocationPicker / Insight cards are hidden for Apple rows.
    expect(screen.queryByText("RPE card")).not.toBeInTheDocument();
    expect(screen.queryByText("Location picker")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Analyze This Workout" })
    ).not.toBeInTheDocument();
  });

  it("shows the Apple Health analysis copy and hides the Load Streams button when source is apple_health", async () => {
    mockedFetchActivity.mockResolvedValue(
      makeActivity({
        name: "Apple Ride",
        sport_type: "Ride",
        source: "apple_health",
      })
    );
    // Hold the streams promise open so the lazy-load panel stays mounted.
    let resolveStreams: ((v: Record<string, number[]>) => void) | undefined;
    mockedFetchActivityStreams.mockReturnValue(
      new Promise<Record<string, number[]>>((resolve) => {
        resolveStreams = resolve;
      })
    );

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Apple Ride");

    // Streams are auto-fetched for Apple — no manual "Load Streams" button.
    expect(
      screen.queryByRole("button", { name: "Load Streams" })
    ).not.toBeInTheDocument();

    resolveStreams?.({});
  });

  it("skips the /weather call entirely for Apple Health workouts", async () => {
    mockedFetchActivity.mockResolvedValue(
      makeActivity({
        name: "Apple Run",
        sport_type: "Run",
        source: "apple_health",
      })
    );
    mockedFetchActivityStreams.mockResolvedValue({});

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Apple Run");

    // The Strava-only /activities/{id}/weather endpoint must not be hit
    // for Apple Health rows — it 404s and is a wasted network round-trip.
    expect(mockedGetActivityWeather).not.toHaveBeenCalled();
  });

  it("re-fetches streams when navigating between Apple Health detail pages", async () => {
    // Two Apple workouts back-to-back. The bug: streams state from workout
    // A would leak into workout B because the auto-fetch effect guarded on
    // streams === null but never reset on activityId change.
    setRouteId(7);
    mockedFetchActivity.mockImplementation(async (id: number) =>
      makeActivity({
        id,
        name: id === 7 ? "Apple Run A" : "Apple Run B",
        sport_type: "Run",
        source: "apple_health",
      })
    );

    const streamsA = { time: [0, 60], heartrate: [120, 125] };
    const streamsB = { time: [0, 30], heartrate: [150, 155] };
    mockedFetchActivityStreams.mockImplementation(async (id: number) =>
      id === 7 ? streamsA : streamsB
    );

    const { rerender } = renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Apple Run A");
    await waitFor(() =>
      expect(mockedFetchActivityStreams).toHaveBeenCalledWith(7, null)
    );

    // Simulate navigation: same component, new URL param.
    setRouteId(11);
    rerender(<ActivityDetailPage />);
    await screen.findByText("Apple Run B");

    // The new id must trigger its own streams fetch — proves the reset
    // effect cleared the prior workout's stream state.
    await waitFor(() =>
      expect(mockedFetchActivityStreams).toHaveBeenCalledWith(11, null)
    );
  });

  it("passes ?source=apple_health through to fetchActivity and renders the Apple branch", async () => {
    // Regression for docs/bugs/apple-watch-routing-collision.md: when the
    // History row navigates with ?source=apple_health, ActivityDetail must
    // forward that to the API so the backend resolves the Apple HDP row
    // (not the colliding Strava activity id).
    setRouteId(123);
    setRouteSearch("?source=apple_health");

    mockedFetchActivity.mockResolvedValue(
      makeActivity({
        id: 123,
        name: "Apple Strength",
        sport_type: "strength",
        source: "apple_health",
        start_lat: null,
        start_lng: null,
      })
    );
    mockedFetchActivityStreams.mockResolvedValue({});

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Apple Strength");

    // 1. The fetch was called with the explicit Apple-Health source so the
    //    backend can disambiguate from a colliding Strava activity id. The
    //    third argument is the user's unit preference, forwarded so the
    //    backend can re-bin Apple splits in miles vs kilometers.
    expect(mockedFetchActivity).toHaveBeenCalledWith(123, "apple_health", "imperial");

    // 2. The Apple branch renders: no RPE card, no LocationPicker, no
    //    "Analyze This Workout" insight button. (See ActivityDetail.tsx
    //    lines 145-171 — these panels are gated on source !== apple_health.)
    expect(screen.queryByText("RPE card")).not.toBeInTheDocument();
    expect(screen.queryByText("Location picker")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Analyze This Workout" })
    ).not.toBeInTheDocument();

    // 3. Streams are auto-fetched for Apple, also with the source forwarded.
    await waitFor(() =>
      expect(mockedFetchActivityStreams).toHaveBeenCalledWith(123, "apple_health")
    );
  });

  it("passes ?source=strava through to fetchActivity when the URL marks Strava explicitly", async () => {
    setRouteId(123);
    setRouteSearch("?source=strava");

    mockedFetchActivity.mockResolvedValue(
      makeActivity({
        id: 123,
        name: "Strava Run",
        sport_type: "Run",
        source: "strava",
      })
    );

    renderWithQuery(<ActivityDetailPage />);
    await screen.findByText("Strava Run");

    expect(mockedFetchActivity).toHaveBeenCalledWith(123, "strava", "imperial");
  });

  describe("prev/next navigation arrows", () => {
    function summary(
      id: number,
      start: string,
      source: ActivitySummary["source"] = "strava",
    ): ActivitySummary {
      return {
        id,
        strava_id: id,
        name: `Run ${id}`,
        sport_type: "Run",
        source,
        external_id: null,
        superseded_by_id: null,
        start_date: start,
        start_date_local: start,
        elapsed_time: 1800,
        moving_time: 1800,
        distance: 5000,
        total_elevation: 0,
        average_hr: 140,
        max_hr: 160,
        average_speed: 3,
        max_speed: 4,
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
        shoe_id: null,
      };
    }

    it("renders both arrows and disables them when current is the only workout", async () => {
      setRouteId(7);
      mockedFetchActivity.mockResolvedValue(makeActivity());
      mockedFetchActivities.mockResolvedValue([
        summary(7, "2026-04-20T18:00:00"),
      ]);
      renderWithQuery(<ActivityDetailPage />);
      await screen.findByText("Evening Run");

      const prev = await screen.findByRole("button", {
        name: "Previous workout",
      });
      const next = await screen.findByRole("button", {
        name: "Next workout",
      });
      await waitFor(() => expect(prev).toBeDisabled());
      expect(next).toBeDisabled();
    });

    it("clicking prev/next navigates to /activities/{id}?source=... with source preserved", async () => {
      setRouteId(7);
      setRouteSearch("?source=strava");
      mockedFetchActivity.mockResolvedValue(makeActivity({ source: "strava" }));
      mockedFetchActivities.mockResolvedValue([
        summary(10, "2026-04-22T18:00:00", "strava"), // newer → next
        summary(7, "2026-04-20T18:00:00", "strava"), // current
        summary(5, "2026-04-18T18:00:00", "apple_health"), // older → prev
      ]);
      renderWithQuery(<ActivityDetailPage />);
      await screen.findByText("Evening Run");

      const prev = await screen.findByRole("button", {
        name: "Previous workout",
      });
      const next = await screen.findByRole("button", {
        name: "Next workout",
      });
      await waitFor(() => expect(prev).not.toBeDisabled());
      await waitFor(() => expect(next).not.toBeDisabled());

      fireEvent.click(prev);
      expect(mockNavigate).toHaveBeenCalledWith(
        "/activities/5?source=apple_health",
      );

      mockNavigate.mockClear();
      fireEvent.click(next);
      expect(mockNavigate).toHaveBeenCalledWith(
        "/activities/10?source=strava",
      );
    });
  });
});
