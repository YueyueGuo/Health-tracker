import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/dashboard", () => ({
  fetchDashboardOverview: vi.fn(),
}));

vi.mock("../api/sync", () => ({
  triggerSync: vi.fn(),
}));

vi.mock("../hooks/useUnits", () => ({
  useUnits: () => ({ units: "imperial" }),
}));

vi.mock("./WeeklySummaryCards", () => ({
  default: () => <div>Weekly summary cards</div>,
}));

vi.mock("./RecommendationCard", () => ({
  default: () => <div>Recommendation card</div>,
}));

vi.mock("./LatestWorkoutCard", () => ({
  default: () => <div>Latest workout card</div>,
}));

import type { DashboardOverview } from "../api/dashboard";
import { fetchDashboardOverview } from "../api/dashboard";
import { triggerSync } from "../api/sync";
import Dashboard from "./Dashboard";

const mockedFetchDashboardOverview = vi.mocked(fetchDashboardOverview);
const mockedTriggerSync = vi.mocked(triggerSync);

const overview: DashboardOverview = {
  weekly_stats: [
    {
      week_start: "2026-04-13",
      week_end: "2026-04-19",
      total_activities: 5,
      total_distance_km: 31.1,
      total_time_minutes: 342,
      total_calories: 2450,
      sport_breakdown: {
        Run: 3,
        Ride: 1,
        WeightTraining: 1,
      },
    },
  ],
  recent_sleep: [
    {
      date: "2026-04-18",
      source: "eight_sleep",
      sleep_score: 72,
      total_duration: 420,
      deep_sleep: null,
      rem_sleep: null,
      light_sleep: null,
      awake_time: null,
      hrv: null,
      avg_hr: null,
      respiratory_rate: null,
    },
    {
      date: "2026-04-19",
      source: "eight_sleep",
      sleep_score: 91.2,
      total_duration: 485,
      deep_sleep: null,
      rem_sleep: null,
      light_sleep: null,
      awake_time: null,
      hrv: null,
      avg_hr: null,
      respiratory_rate: null,
    },
  ],
  recent_recovery: [
    {
      date: "2026-04-18",
      recovery_score: 55,
      resting_hr: null,
      hrv: 44,
      spo2: null,
      strain_score: null,
    },
    {
      date: "2026-04-19",
      recovery_score: 72.6,
      resting_hr: null,
      hrv: 58.4,
      spo2: null,
      strain_score: null,
    },
  ],
  training_load: {
    ctl: [],
    atl: [],
    tsb: [],
    daily_load: [],
  },
};

describe("Dashboard", () => {
  beforeEach(() => {
    mockedFetchDashboardOverview.mockResolvedValue(overview);
    mockedTriggerSync.mockResolvedValue({ status: "started", synced: {} });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders overview cards from nested dashboard payloads", async () => {
    render(<Dashboard />);

    await screen.findByRole("heading", { name: "Dashboard" });

    expect(screen.getByText("Recommendation card")).toBeInTheDocument();
    expect(screen.getByText("Latest workout card")).toBeInTheDocument();
    expect(screen.getByText("Weekly summary cards")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("19.3 mi")).toBeInTheDocument();
    expect(screen.getByText("5h 42m")).toBeInTheDocument();
    expect(screen.getByText("2450 cal")).toBeInTheDocument();
    expect(screen.getByText("91")).toBeInTheDocument();
    expect(screen.getByText("8h 5m")).toBeInTheDocument();
    expect(screen.getByText("73%")).toBeInTheDocument();
    expect(screen.getByText("HRV: 58ms")).toBeInTheDocument();
    expect(
      screen.getByText((_, node) => node?.textContent === "Run: 3 sessions")
    ).toBeInTheDocument();
    expect(
      screen.getByText((_, node) => node?.textContent === "Ride: 1 session")
    ).toBeInTheDocument();
  });

  it("triggers a sync and reloads the overview", async () => {
    render(<Dashboard />);

    await screen.findByRole("heading", { name: "Dashboard" });
    fireEvent.click(screen.getByRole("button", { name: "Sync Data" }));

    await waitFor(() => expect(mockedTriggerSync).toHaveBeenCalledWith("all"));
    await waitFor(() => expect(mockedFetchDashboardOverview).toHaveBeenCalledTimes(2));
  });
});
