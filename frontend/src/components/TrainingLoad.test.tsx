import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("recharts", () => {
  const passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  const lineChart = ({
    children,
    data,
  }: {
    children?: ReactNode;
    data?: unknown;
  }) => (
    <div data-testid="fitness-chart">
      {JSON.stringify(data)}
      {children}
    </div>
  );
  const barChart = ({
    children,
    data,
  }: {
    children?: ReactNode;
    data?: unknown;
  }) => (
    <div data-testid="load-chart">
      {JSON.stringify(data)}
      {children}
    </div>
  );

  return {
    ResponsiveContainer: passthrough,
    LineChart: lineChart,
    Line: () => <div />,
    BarChart: barChart,
    Bar: () => <div />,
    XAxis: () => <div />,
    YAxis: () => <div />,
    CartesianGrid: () => <div />,
    Tooltip: () => <div />,
    Legend: () => <div />,
    ReferenceLine: () => <div />,
  };
});

vi.mock("../api/dashboard", () => ({
  fetchDashboardOverview: vi.fn(),
}));

import type { DashboardOverview } from "../api/dashboard";
import { fetchDashboardOverview } from "../api/dashboard";
import TrainingLoad from "./TrainingLoad";

const mockedFetchDashboardOverview = vi.mocked(fetchDashboardOverview);

const overview: DashboardOverview = {
  weekly_stats: [
    {
      week_start: "2026-04-13",
      week_end: "2026-04-19",
      total_activities: 4,
      total_distance_km: 42.2,
      total_time_minutes: 315,
      total_calories: 2100,
      sport_breakdown: { Run: 4 },
    },
  ],
  recent_sleep: [],
  recent_recovery: [],
  training_load: {
    ctl: [
      { date: "2026-04-18", value: 41.2 },
      { date: "2026-04-19", value: 42.5 },
    ],
    atl: [
      { date: "2026-04-18", value: 52.4 },
      { date: "2026-04-19", value: 48.9 },
    ],
    tsb: [
      { date: "2026-04-18", value: -11.2 },
      { date: "2026-04-19", value: -6.4 },
    ],
    daily_load: [
      { date: "2026-04-18", value: 74 },
      { date: "2026-04-19", value: 22 },
    ],
  },
};

describe("TrainingLoad", () => {
  beforeEach(() => {
    mockedFetchDashboardOverview.mockResolvedValue(overview);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders chart-ready training load data and weekly volume rows", async () => {
    render(<TrainingLoad />);

    await screen.findByRole("heading", { name: "Training Load" });

    expect(screen.getByTestId("fitness-chart")).toHaveTextContent(
      '"fitness":41.2'
    );
    expect(screen.getByTestId("fitness-chart")).toHaveTextContent(
      '"fatigue":52.4'
    );
    expect(screen.getByTestId("fitness-chart")).toHaveTextContent('"form":-6.4');
    expect(screen.getByTestId("load-chart")).toHaveTextContent('"load":74');
    expect(screen.getByRole("cell", { name: "2026-04-13" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "4" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "42.2 km" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "5h 15m" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "2100" })).toBeInTheDocument();
  });

  it("shows an empty state for the backend no-activity training load shape", async () => {
    mockedFetchDashboardOverview.mockResolvedValue({
      ...overview,
      training_load: {
        ctl: [
          { date: "2026-04-18", value: 0 },
          { date: "2026-04-19", value: 0 },
        ],
        atl: [
          { date: "2026-04-18", value: 0 },
          { date: "2026-04-19", value: 0 },
        ],
        tsb: [
          { date: "2026-04-18", value: 0 },
          { date: "2026-04-19", value: 0 },
        ],
        daily_load: [],
      },
    });

    render(<TrainingLoad />);

    expect(
      await screen.findByText("No training data available.")
    ).toBeInTheDocument();
  });
});
