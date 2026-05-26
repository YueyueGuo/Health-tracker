// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "../../test/renderWithQuery";

vi.mock("react-router-dom", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useOutletContext: () => ({
      dateStr: "2026-05-26",
      isToday: true,
      selectedDate: new Date("2026-05-26T12:00:00"),
    }),
  };
});

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: "imperial" }),
  formatDistanceShort: (m: number) => `${(m / 1609.34).toFixed(1)} mi`,
  formatElevation: (m: number) => `${Math.round(m)} ft`,
}));

const fetchLatestWorkoutInsightMock = vi.fn();
const fetchStrengthSessionOptionalMock = vi.fn();

vi.mock("../../api/insights", () => ({
  fetchLatestWorkoutInsight: (...args: unknown[]) =>
    fetchLatestWorkoutInsightMock(...args),
}));

vi.mock("../../api/strength", () => ({
  fetchStrengthSessionOptional: (...args: unknown[]) =>
    fetchStrengthSessionOptionalMock(...args),
}));

import { YesterdayActivityCard } from "./YesterdayActivityCard";

function buildWorkout(
  overrides: Partial<Record<string, unknown>> = {},
): Record<string, unknown> {
  return {
    id: 42,
    strava_id: null,
    source: "strava",
    name: "Morning Run",
    sport_type: "Run",
    classification_type: null,
    classification_flags: [],
    start_date: "2026-05-26T13:00:00Z",
    start_date_local: "2026-05-26T08:00:00",
    distance_m: 8047,
    moving_time_s: 2700,
    elapsed_time_s: 2700,
    total_elevation_m: 0,
    avg_hr: 150,
    max_hr: 170,
    avg_speed_ms: null,
    pace: "9:00/mi",
    avg_power_w: null,
    weighted_avg_power_w: null,
    kilojoules: null,
    suffer_score: 80,
    calories: 400,
    laps: [],
    hr_zones: null,
    hr_drift: null,
    pace_hr_decoupling: null,
    power_hr_decoupling: null,
    weather: null,
    pre_workout_sleep: null,
    historical_comparison: null,
    ...overrides,
  };
}

function buildResponse(workout: Record<string, unknown>) {
  return {
    activity_id: workout.id,
    workout,
    insight: null,
    model: "mock",
    generated_at: "2026-05-26T08:00:00",
    cached: false,
  };
}

describe("YesterdayActivityCard", () => {
  it("tags the source as Apple when workout.source is apple_health", async () => {
    fetchLatestWorkoutInsightMock.mockResolvedValueOnce(
      buildResponse(buildWorkout({ source: "apple_health" })),
    );
    fetchStrengthSessionOptionalMock.mockResolvedValueOnce(null);

    renderWithQuery(
      <MemoryRouter>
        <YesterdayActivityCard />
      </MemoryRouter>,
    );

    const badge = await screen.findByTestId("source-badge-apple");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Apple");
    expect(screen.queryByTestId("source-badge-strava")).not.toBeInTheDocument();
  });

  it("tags the source as Strava when workout.source is strava", async () => {
    fetchLatestWorkoutInsightMock.mockResolvedValueOnce(
      buildResponse(buildWorkout({ source: "strava" })),
    );
    fetchStrengthSessionOptionalMock.mockResolvedValueOnce(null);

    renderWithQuery(
      <MemoryRouter>
        <YesterdayActivityCard />
      </MemoryRouter>,
    );

    const badge = await screen.findByTestId("source-badge-strava");
    expect(badge).toHaveTextContent("Strava");
    expect(screen.queryByTestId("source-badge-apple")).not.toBeInTheDocument();
  });

  it("links the cardio summary to the activity detail page", async () => {
    fetchLatestWorkoutInsightMock.mockResolvedValueOnce(
      buildResponse(
        buildWorkout({ id: 99, source: "apple_health", name: "Apple Run" }),
      ),
    );
    fetchStrengthSessionOptionalMock.mockResolvedValueOnce(null);

    renderWithQuery(
      <MemoryRouter>
        <YesterdayActivityCard />
      </MemoryRouter>,
    );

    const link = await screen.findByRole("link", {
      name: /view apple run detail/i,
    });
    expect(link).toHaveAttribute(
      "href",
      "/activities/99?source=apple_health",
    );
  });

  it("preserves the lifting link when both cardio and strength are present", async () => {
    fetchLatestWorkoutInsightMock.mockResolvedValueOnce(
      buildResponse(
        buildWorkout({
          id: 7,
          source: "strava",
          name: "Lift Day",
          sport_type: "WeightTraining",
        }),
      ),
    );
    fetchStrengthSessionOptionalMock.mockResolvedValueOnce({
      date: "2026-05-26",
      activity_id: 7,
      sets: [],
      exercises: [
        {
          name: "Bench Press",
          sets: [{ reps: 5, weight_kg: 60 }],
          max_weight: 60,
          total_volume: 300,
          est_1rm: 65,
        },
      ],
      link: null,
      segmentation: null,
      hr_curve: null,
      segment_markers: null,
      activity_start_iso: null,
    });

    renderWithQuery(
      <MemoryRouter>
        <YesterdayActivityCard />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: "View lifting session detail" }),
      ).toHaveAttribute("href", "/workouts/lifting/2026-05-26");
    });
    expect(
      screen.getByRole("link", { name: /view lift day detail/i }),
    ).toHaveAttribute("href", "/activities/7?source=strava");
  });
});
