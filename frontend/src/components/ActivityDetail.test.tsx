import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "7" }),
  useNavigate: () => vi.fn(),
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
  fetchActivityStreams: vi.fn(),
  reclassifyActivity: vi.fn(),
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

vi.mock("./WeatherCard", () => ({
  default: () => <div>Weather card expanded</div>,
}));

import ActivityDetailPage from "./ActivityDetail";
import {
  type ActivityDetail as ActivityDetailResponse,
  fetchActivity,
  fetchActivityStreams,
} from "../api/activities";
import { fetchLatestWorkoutInsight } from "../api/insights";
import { getActivityWeather } from "../api/weather";

const mockedFetchActivity = vi.mocked(fetchActivity);
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
    mockedGetActivityWeather.mockResolvedValue(null);
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

    render(<ActivityDetailPage />);

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
      expect(mockedFetchActivityStreams).toHaveBeenCalledWith(7)
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

    render(<ActivityDetailPage />);
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

    render(<ActivityDetailPage />);
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

    render(<ActivityDetailPage />);
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

    render(<ActivityDetailPage />);
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

    render(<ActivityDetailPage />);
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

    render(<ActivityDetailPage />);
    await screen.findByText("Sunrise Hike");
    // Run layout shows Avg Pace; Ride/Strength do not.
    expect(screen.getByText("Avg Pace")).toBeInTheDocument();
  });
});
