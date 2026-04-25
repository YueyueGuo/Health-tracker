import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "7" }),
}));

vi.mock("recharts", () => {
  const passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>;

  return {
    ResponsiveContainer: passthrough,
    LineChart: ({ children }: { children?: ReactNode }) => (
      <div data-testid="line-chart">{children}</div>
    ),
    Line: () => <div />,
    XAxis: () => <div />,
    YAxis: () => <div />,
    CartesianGrid: () => <div />,
    Tooltip: () => <div />,
    Legend: () => <div />,
    BarChart: passthrough,
    Bar: () => <div />,
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

vi.mock("../hooks/useUnits", () => ({
  useUnits: () => ({ units: "metric" }),
  formatDistance: (meters: number | null | undefined) =>
    meters == null ? "—" : `${Math.round(meters)} m`,
  formatElevation: (meters: number | null | undefined) =>
    meters == null ? "—" : `${Math.round(meters)} m`,
  formatPaceOrSpeed: () => "5:00 /km",
  isCyclingSport: () => false,
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
  default: () => <div>Weather card</div>,
}));

import ActivityDetail from "./ActivityDetail";
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

const activity: ActivityDetailResponse = {
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
};

describe("ActivityDetail", () => {
  beforeEach(() => {
    mockedFetchActivity.mockResolvedValue(activity);
    mockedGetActivityWeather.mockResolvedValue(null);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loads insight and streams on demand", async () => {
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
        notable_segments: [{ label: "Middle 2 km", detail: "Best rhythm of the run." }],
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

    render(<ActivityDetail />);

    await screen.findByText("Evening Run");

    fireEvent.click(screen.getByRole("button", { name: "Analyze This Workout" }));
    await screen.findByText("Strong aerobic work");
    expect(mockedFetchLatestWorkoutInsight).toHaveBeenCalledWith({ activityId: 7 });
    expect(screen.getByText("Model: gpt-4o")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load Streams" }));
    await waitFor(() =>
      expect(mockedFetchActivityStreams).toHaveBeenCalledWith(7)
    );
    expect(screen.getByTestId("line-chart")).toBeInTheDocument();
  });

  it("surfaces lazy insight and stream errors", async () => {
    mockedFetchLatestWorkoutInsight.mockRejectedValue(new Error("Insight unavailable"));
    mockedFetchActivityStreams.mockRejectedValue(new Error("Streams unavailable"));

    render(<ActivityDetail />);

    await screen.findByText("Evening Run");

    fireEvent.click(screen.getByRole("button", { name: "Analyze This Workout" }));
    await screen.findByText("Insight unavailable");

    fireEvent.click(screen.getByRole("button", { name: "Load Streams" }));
    await screen.findByText("Streams unavailable");
  });
});
