import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ActivityLap } from "../../api/activities";

// Mutable units value so each test can choose imperial vs metric without
// pulling in the full UnitsProvider context.
let currentUnits: "imperial" | "metric" = "imperial";

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: currentUnits }),
}));

import SplitsTable from "./SplitsTable";

function lap(overrides: Partial<ActivityLap> = {}): ActivityLap {
  return {
    lap_index: 1,
    name: null,
    elapsed_time: 600,
    moving_time: 600,
    distance: 1000,
    start_date: null,
    average_speed: 3,
    max_speed: null,
    average_heartrate: 140,
    max_heartrate: 160,
    average_cadence: null,
    average_watts: null,
    total_elevation_gain: 0,
    pace_zone: null,
    hr_zone: null,
    split: null,
    start_index: null,
    end_index: null,
    ...overrides,
  };
}

describe("SplitsTable", () => {
  afterEach(() => {
    currentUnits = "imperial";
  });

  it("renders distances in miles when units are imperial and the lap is a mile-bucketed split", () => {
    currentUnits = "imperial";
    render(
      <SplitsTable
        variant="run"
        laps={[lap({ distance: 1609.344 })]}
        splitsSynthetic
      />,
    );
    // distanceWithUnit(1609.344, "imperial") → "1.00 mi"
    expect(screen.getByText("1.00 mi")).toBeInTheDocument();
  });

  it("renders distances in kilometers when units are metric and the lap is a 1000 m bucket", () => {
    currentUnits = "metric";
    render(
      <SplitsTable
        variant="run"
        laps={[lap({ distance: 1000 })]}
        splitsSynthetic
      />,
    );
    // distanceWithUnit(1000, "metric") → "1.00 km"
    expect(screen.getByText("1.00 km")).toBeInTheDocument();
  });

  it("uses softened caption mentioning 1 mi splits when imperial and splitsSynthetic is true", () => {
    currentUnits = "imperial";
    render(
      <SplitsTable
        variant="run"
        laps={[lap({ distance: 1609.344 })]}
        splitsSynthetic
      />,
    );
    // The new copy should mention 1 mi splits and explain that HAE can't
    // expose lap markers — not the old "did not provide" wording.
    expect(screen.getByText(/1 mi splits/i)).toBeInTheDocument();
    expect(screen.getByText(/doesn't expose lap markers/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/did not provide lap markers/i),
    ).not.toBeInTheDocument();
  });

  it("uses softened caption mentioning 1 km splits when metric and splitsSynthetic is true", () => {
    currentUnits = "metric";
    render(
      <SplitsTable
        variant="run"
        laps={[lap({ distance: 1000 })]}
        splitsSynthetic
      />,
    );
    expect(screen.getByText(/1 km splits/i)).toBeInTheDocument();
  });

  it("omits the auto-split caption entirely when splitsSynthetic is false", () => {
    currentUnits = "imperial";
    render(<SplitsTable variant="run" laps={[lap({ distance: 1609.344 })]} />);
    expect(screen.queryByText(/Auto-split/i)).not.toBeInTheDocument();
  });
});
