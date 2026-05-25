// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DeviceWorkoutPanel from "./DeviceWorkoutPanel";
import type {
  StrengthSessionLink,
  StrengthSessionSegmentation,
} from "../../api/strength";

function makeLink(over: Partial<StrengthSessionLink> = {}): StrengthSessionLink {
  return {
    source: "strava",
    ref_id: 123,
    name: "Garage lift",
    sport: "WeightTraining",
    start_iso: "2026-05-25T17:30:00",
    duration_s: 3600,
    avg_hr: 132,
    max_hr: 168,
    ...over,
  };
}

function makeSeg(
  over: Partial<StrengthSessionSegmentation> = {}
): StrengthSessionSegmentation {
  return {
    status: "ok",
    detected_count: 8,
    target_count: 8,
    ...over,
  };
}

describe("DeviceWorkoutPanel", () => {
  it("renders the unlinked state with a Link button", () => {
    const onOpenPicker = vi.fn();
    render(
      <DeviceWorkoutPanel
        date="2026-05-25"
        link={null}
        segmentation={null}
        onOpenPicker={onOpenPicker}
        onUnlink={vi.fn()}
        onRetry={vi.fn()}
      />
    );
    expect(
      screen.getByText("No device workout linked.")
    ).toBeInTheDocument();
    const btn = screen.getByTestId("device-workout-link-btn");
    fireEvent.click(btn);
    expect(onOpenPicker).toHaveBeenCalledTimes(1);
  });

  it("renders a loading state when segmentation is pending", () => {
    render(
      <DeviceWorkoutPanel
        date="2026-05-25"
        link={makeLink()}
        segmentation={makeSeg({ status: "pending" })}
        onOpenPicker={vi.fn()}
        onUnlink={vi.fn()}
        onRetry={vi.fn()}
      />
    );
    expect(
      screen.getByTestId("device-workout-loading")
    ).toBeInTheDocument();
    expect(screen.getByText(/Loading heart-rate stream/i)).toBeInTheDocument();
  });

  it("renders linked + ok with name, HR summary and Change/Unlink", () => {
    render(
      <DeviceWorkoutPanel
        date="2026-05-25"
        link={makeLink({ name: "Afternoon lift" })}
        segmentation={makeSeg({ status: "ok" })}
        onOpenPicker={vi.fn()}
        onUnlink={vi.fn()}
        onRetry={vi.fn()}
      />
    );
    expect(screen.getByText("Afternoon lift")).toBeInTheDocument();
    expect(screen.getByTestId("source-badge-strava")).toBeInTheDocument();
    expect(screen.getByText(/132 \/ 168/)).toBeInTheDocument();
    expect(
      screen.getByTestId("device-workout-change-btn")
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("device-workout-unlink-btn")
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("device-workout-retry-btn")
    ).not.toBeInTheDocument();
  });

  it("renders degraded state with reason and a Retry button", () => {
    const onRetry = vi.fn().mockResolvedValue(undefined);
    render(
      <DeviceWorkoutPanel
        date="2026-05-25"
        link={makeLink({ source: "apple_health" })}
        segmentation={makeSeg({ status: "no_curve", detected_count: 0 })}
        onOpenPicker={vi.fn()}
        onUnlink={vi.fn()}
        onRetry={onRetry}
      />
    );
    const degraded = screen.getByTestId("device-workout-degraded");
    expect(degraded.textContent).toMatch(/no HR time series/i);
    const retry = screen.getByTestId("device-workout-retry-btn");
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledTimes(1);
    // Apple Health badge is used for the apple_health source.
    expect(screen.getByTestId("source-badge-apple")).toBeInTheDocument();
  });

  it("shows the no_stream reason for Strava streams pending fetch", () => {
    render(
      <DeviceWorkoutPanel
        date="2026-05-25"
        link={makeLink()}
        segmentation={makeSeg({ status: "no_stream", detected_count: 0 })}
        onOpenPicker={vi.fn()}
        onUnlink={vi.fn()}
        onRetry={vi.fn()}
      />
    );
    const degraded = screen.getByTestId("device-workout-degraded");
    expect(degraded.textContent).toMatch(/Strava heart-rate stream/i);
  });
});
