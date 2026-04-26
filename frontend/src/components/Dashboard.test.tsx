import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/dashboard", () => ({
  fetchDashboardToday: vi.fn(),
  ACWR_TOOLTIP: "ACWR tooltip text",
}));

vi.mock("../api/sync", () => ({
  triggerSync: vi.fn(),
}));

vi.mock("../hooks/useUnits", () => ({
  useUnits: () => ({ units: "imperial" }),
  formatTemperature: (c: number | null | undefined) =>
    c == null ? "—" : `${Math.round(c * (9 / 5) + 32)}°F`,
  formatWindSpeed: (m: number | null | undefined) =>
    m == null ? "—" : `${(m * 2.237).toFixed(1)} mph`,
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

import type { DashboardToday } from "../api/dashboard";
import { fetchDashboardToday } from "../api/dashboard";
import { triggerSync } from "../api/sync";
import Dashboard from "./Dashboard";

const mockedFetchDashboardToday = vi.mocked(fetchDashboardToday);
const mockedTriggerSync = vi.mocked(triggerSync);

const today: DashboardToday = {
  as_of: "2026-04-25T08:12:00-04:00",
  sleep: {
    last_night_score: 89,
    last_night_duration_min: 500,
    last_night_deep_min: 92,
    last_night_rem_min: 118,
    last_night_date: "2026-04-25",
  },
  recovery: {
    today_hrv: 77.3,
    today_resting_hr: 49,
    hrv_baseline_7d: 72.1,
    hrv_trend: "up",
    hrv_source: "eight_sleep",
  },
  training: {
    yesterday_stress: 78,
    week_to_date_load: 412,
    acwr: 1.12,
    acwr_band: "optimal",
    days_since_hard: 2,
  },
  environment: {
    forecast: { temp_c: 20, high_c: 24, low_c: 12, conditions: "Cloudy", wind_ms: 4 },
    air_quality: { us_aqi: 42, european_aqi: null, pollen: null },
  },
};

describe("Dashboard", () => {
  beforeEach(() => {
    mockedFetchDashboardToday.mockResolvedValue(today);
    mockedTriggerSync.mockResolvedValue({ status: "started", synced: {} });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the four today tiles plus retained cards", async () => {
    render(<Dashboard />);

    await screen.findByRole("heading", { name: "Dashboard" });

    expect(screen.getByText("Recommendation card")).toBeInTheDocument();
    expect(screen.getByText("Latest workout card")).toBeInTheDocument();
    expect(screen.getByText("Weekly summary cards")).toBeInTheDocument();

    // Sleep tile
    expect(screen.getByText("89")).toBeInTheDocument();
    expect(screen.getByText("8h 20m")).toBeInTheDocument();

    // Recovery tile
    expect(screen.getByText("77")).toBeInTheDocument();
    expect(screen.getByText("Eight Sleep")).toBeInTheDocument();
    expect(screen.getByLabelText("HRV trend up")).toBeInTheDocument();

    // Training tile
    expect(screen.getByText("412")).toBeInTheDocument();
    expect(screen.getByText(/ACWR 1.12 · optimal/)).toBeInTheDocument();

    // Environment tile
    expect(screen.getByText("AQI 42")).toBeInTheDocument();
    expect(screen.getByText("68°F")).toBeInTheDocument();
  });

  it("triggers a sync and reloads the today payload", async () => {
    render(<Dashboard />);

    await screen.findByRole("heading", { name: "Dashboard" });
    fireEvent.click(screen.getByRole("button", { name: "Sync Data" }));

    await waitFor(() => expect(mockedTriggerSync).toHaveBeenCalledWith("all"));
    await waitFor(() => expect(mockedFetchDashboardToday).toHaveBeenCalledTimes(2));
  });
});
