import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("recharts", () => {
  const passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: passthrough,
    ComposedChart: ({ children }: { children?: ReactNode }) => (
      <div data-testid="composed-chart">{children}</div>
    ),
    Area: () => <div />,
    Line: () => <div />,
    XAxis: () => <div />,
    YAxis: () => <div />,
    Tooltip: () => <div />,
  };
});

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: "imperial" }),
}));

import AnalysisChart from "./AnalysisChart";

describe("AnalysisChart empty state", () => {
  it("shows the Health Auto Export guidance when source is apple_health and streams are empty", () => {
    render(
      <AnalysisChart
        mode="run"
        streams={{}}
        streamsLoading={false}
        streamsError={null}
        onLoadStreams={() => {}}
        streamsCached={false}
        source="apple_health"
      />,
    );

    expect(
      screen.getByText(/No per-sample heart rate data for this workout/i),
    ).toBeInTheDocument();
    // The actionable hint should reference Health Auto Export so the user
    // knows where to flip the setting.
    expect(screen.getByText(/Health Auto Export/i)).toBeInTheDocument();
    // The Strava-style copy must NOT appear for Apple workouts.
    expect(
      screen.queryByText(/No stream data available/i),
    ).not.toBeInTheDocument();
  });

  it("falls back to the generic empty-state copy when source is strava", () => {
    render(
      <AnalysisChart
        mode="run"
        streams={{}}
        streamsLoading={false}
        streamsError={null}
        onLoadStreams={() => {}}
        streamsCached={false}
        source="strava"
      />,
    );

    expect(screen.getByText(/No stream data available/i)).toBeInTheDocument();
    expect(screen.queryByText(/Health Auto Export/i)).not.toBeInTheDocument();
  });

  it("falls back to the generic empty-state copy when source is undefined", () => {
    render(
      <AnalysisChart
        mode="run"
        streams={{}}
        streamsLoading={false}
        streamsError={null}
        onLoadStreams={() => {}}
        streamsCached={false}
      />,
    );

    expect(screen.getByText(/No stream data available/i)).toBeInTheDocument();
    expect(screen.queryByText(/Health Auto Export/i)).not.toBeInTheDocument();
  });
});
