import type { ReactNode } from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UnitsProvider } from "../hooks/useUnits";

vi.mock("recharts", () => {
  const passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  const chart = (testId: string) => ({
    children,
    data,
  }: {
    children?: ReactNode;
    data?: unknown;
  }) => (
    <div data-testid={testId}>
      {JSON.stringify(data)}
      {children}
    </div>
  );

  return {
    ResponsiveContainer: passthrough,
    LineChart: chart("line-chart"),
    ComposedChart: chart("composed-chart"),
    Line: () => <div />,
    BarChart: chart("bar-chart"),
    Bar: () => <div />,
    XAxis: () => <div />,
    YAxis: () => <div />,
    Tooltip: () => <div />,
  };
});

vi.mock("../api/activities", () => ({
  fetchActivities: vi.fn(),
}));
vi.mock("../api/recovery", () => ({
  fetchRecoveryTrends: vi.fn(),
}));
vi.mock("../api/sleep", () => ({
  fetchSleepTrends: vi.fn(),
}));
vi.mock("../api/strength", () => ({
  fetchStrengthExercises: vi.fn(),
  fetchStrengthProgression: vi.fn(),
  fetchStrengthSessions: vi.fn(),
}));

import type { ActivitySummary } from "../api/activities";
import { fetchActivities } from "../api/activities";
import type { RecoveryTrend } from "../api/dashboard";
import { fetchRecoveryTrends } from "../api/recovery";
import type { SleepSession } from "../api/sleep";
import { fetchSleepTrends } from "../api/sleep";
import type { ProgressionPoint, StrengthSession } from "../api/strength";
import {
  fetchStrengthExercises,
  fetchStrengthProgression,
  fetchStrengthSessions,
} from "../api/strength";
import TrainingLoad from "./TrainingLoad";

const mockedFetchActivities = vi.mocked(fetchActivities);
const mockedFetchRecoveryTrends = vi.mocked(fetchRecoveryTrends);
const mockedFetchSleepTrends = vi.mocked(fetchSleepTrends);
const mockedFetchStrengthExercises = vi.mocked(fetchStrengthExercises);
const mockedFetchStrengthProgression = vi.mocked(fetchStrengthProgression);
const mockedFetchStrengthSessions = vi.mocked(fetchStrengthSessions);

const activities: ActivitySummary[] = [
  activity({
    id: 1,
    sport_type: "Run",
    start_date_local: "2026-04-07T07:00:00",
    distance: 8046.72,
    moving_time: 3000,
    suffer_score: 45,
    classification_type: "easy",
  }),
  activity({
    id: 2,
    sport_type: "Run",
    start_date_local: "2026-04-14T07:00:00",
    distance: 16093.44,
    moving_time: 7200,
    suffer_score: 120,
    classification_type: "endurance",
  }),
  activity({
    id: 3,
    sport_type: "Ride",
    start_date_local: "2026-04-16T07:00:00",
    distance: 32186.88,
    moving_time: 3600,
    suffer_score: 95,
    weighted_avg_power: 250,
    classification_type: "intervals",
  }),
];

const recovery: RecoveryTrend[] = [
  {
    date: "2026-04-07",
    recovery_score: 62,
    resting_hr: 58,
    hrv: 42,
    spo2: null,
    strain_score: 8,
  },
  {
    date: "2026-04-16",
    recovery_score: 74,
    resting_hr: 54,
    hrv: 48,
    spo2: null,
    strain_score: 10,
  },
];

const sleep: SleepSession[] = [
  {
    id: 1,
    source: "whoop",
    date: "2026-04-16",
    bed_time: null,
    wake_time: null,
    total_duration: 450,
    deep_sleep: null,
    rem_sleep: null,
    light_sleep: null,
    awake_time: null,
    sleep_score: 80,
    sleep_fitness_score: null,
    avg_hr: 55,
    hrv: 49,
    respiratory_rate: null,
    bed_temp: null,
    tnt_count: null,
    latency: null,
    sleep_need_baseline_min: 480,
    sleep_debt_min: 30,
  },
];

const progression: ProgressionPoint[] = [
  {
    date: "2026-04-01",
    max_weight_kg: 100,
    est_1rm_kg: 110,
    total_volume_kg: 3000,
    top_set_reps: 5,
  },
  {
    date: "2026-04-20",
    max_weight_kg: 110,
    est_1rm_kg: 121,
    total_volume_kg: 3600,
    top_set_reps: 5,
  },
];

const strengthSessions: StrengthSession[] = [
  {
    date: "2026-04-20",
    exercise_count: 3,
    total_sets: 12,
    total_volume_kg: 10000,
    activity_id: null,
  },
];

describe("TrainingLoad", () => {
  beforeEach(() => {
    mockedFetchActivities.mockResolvedValue(activities);
    mockedFetchRecoveryTrends.mockResolvedValue(recovery);
    mockedFetchSleepTrends.mockResolvedValue(sleep);
    mockedFetchStrengthExercises.mockResolvedValue(["Back Squat"]);
    mockedFetchStrengthProgression.mockResolvedValue(progression);
    mockedFetchStrengthSessions.mockResolvedValue(strengthSessions);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the live trends sections with chart-ready data", async () => {
    renderTrends();

    await screen.findByRole("heading", { name: "Trends" });

    expect(mockedFetchActivities).toHaveBeenCalledWith({ days: 90, limit: 200 });
    expect(mockedFetchRecoveryTrends).toHaveBeenCalledWith(90);
    expect(mockedFetchSleepTrends).toHaveBeenCalledWith(90);
    await waitFor(() =>
      expect(mockedFetchStrengthProgression).toHaveBeenCalledWith(
        "Back Squat",
        90
      )
    );

    expect(screen.getByRole("heading", { name: "Macro Analysis" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Cardio" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Strength" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recovery" })).toBeInTheDocument();
    expect(screen.getByText(/HRV is up 6\.5 ms/)).toBeInTheDocument();
    expect(screen.getByText(/10\.0/)).toBeInTheDocument();
    expect(screen.getByText(/243/)).toBeInTheDocument();

    expect(screen.getAllByTestId("bar-chart")[0]).toHaveTextContent(
      '"distance":10'
    );
    expect(screen.getAllByTestId("line-chart")[1]).toHaveTextContent(
      '"maxWeight":242'
    );
    expect(screen.getAllByTestId("composed-chart")[0]).toHaveTextContent(
      '"recovery":74'
    );
  });

  it("updates cardio filters for ride VO2 power data", async () => {
    renderTrends();

    await screen.findByRole("heading", { name: "Trends" });
    fireEvent.click(screen.getByRole("button", { name: /Ride/i }));
    fireEvent.change(screen.getByLabelText("Cardio workout type"), {
      target: { value: "VO2 Max" },
    });

    expect(
      screen.getByRole("heading", { name: "Power Progression" })
    ).toBeInTheDocument();
    const cardioSection = screen.getByRole("heading", { name: "Cardio" })
      .parentElement?.parentElement;
    expect(cardioSection).not.toBeNull();
    expect(within(cardioSection!).getAllByTestId("line-chart")[0]).toHaveTextContent(
      '"np":250'
    );
  });

  it("shows empty states when live trend data is sparse", async () => {
    mockedFetchActivities.mockResolvedValue([]);
    mockedFetchRecoveryTrends.mockResolvedValue([]);
    mockedFetchSleepTrends.mockResolvedValue([]);
    mockedFetchStrengthExercises.mockResolvedValue([]);
    mockedFetchStrengthProgression.mockResolvedValue([]);
    mockedFetchStrengthSessions.mockResolvedValue([]);

    renderTrends();

    expect(await screen.findByText(/Add more cardio/)).toBeInTheDocument();
    expect(screen.getByText("No matching cardio workouts in this range.")).toBeInTheDocument();
    expect(screen.getByText("No strength volume logged yet.")).toBeInTheDocument();
    expect(screen.getByText("No recovery trend data in this range.")).toBeInTheDocument();
  });
});

function renderTrends() {
  return render(
    <UnitsProvider>
      <TrainingLoad />
    </UnitsProvider>
  );
}

function activity(patch: Partial<ActivitySummary>): ActivitySummary {
  return {
    id: 1,
    strava_id: 1,
    name: "Workout",
    sport_type: "Run",
    start_date: null,
    start_date_local: null,
    elapsed_time: null,
    moving_time: null,
    distance: null,
    total_elevation: null,
    average_hr: null,
    max_hr: null,
    average_speed: null,
    max_speed: null,
    average_power: null,
    max_power: null,
    weighted_avg_power: null,
    average_cadence: null,
    calories: null,
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
    ...patch,
  };
}
