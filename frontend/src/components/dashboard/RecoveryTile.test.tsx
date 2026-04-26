import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RecoveryTodayPayload } from "../../api/dashboard";
import RecoveryTile from "./RecoveryTile";

function payload(overrides: Partial<RecoveryTodayPayload> = {}): RecoveryTodayPayload {
  return {
    today_hrv: 77.3,
    today_resting_hr: 49.2,
    hrv_baseline_7d: 72.1,
    hrv_trend: "up",
    hrv_source: "eight_sleep",
    ...overrides,
  };
}

describe("RecoveryTile", () => {
  it("renders HRV value, RHR, baseline, source pill, and trend arrow", () => {
    render(<RecoveryTile data={payload()} />);
    expect(screen.getByText("77")).toBeInTheDocument();
    expect(screen.getByText(/49 bpm RHR/)).toBeInTheDocument();
    expect(screen.getByText(/7d avg 72 ms/)).toBeInTheDocument();
    expect(screen.getByText("Eight Sleep")).toBeInTheDocument();
    const arrow = screen.getByLabelText("HRV trend up");
    expect(arrow).toHaveTextContent("↑");
    expect(arrow).toHaveStyle({ color: "var(--green)" });
  });

  it("renders down trend in red", () => {
    render(<RecoveryTile data={payload({ hrv_trend: "down" })} />);
    const arrow = screen.getByLabelText("HRV trend down");
    expect(arrow).toHaveTextContent("↓");
    expect(arrow).toHaveStyle({ color: "var(--red)" });
  });

  it("renders flat trend muted", () => {
    render(<RecoveryTile data={payload({ hrv_trend: "flat" })} />);
    const arrow = screen.getByLabelText("HRV trend flat");
    expect(arrow).toHaveTextContent("→");
    expect(arrow).toHaveStyle({ color: "var(--text-muted)" });
  });

  it("shows Whoop source label", () => {
    render(<RecoveryTile data={payload({ hrv_source: "whoop" })} />);
    expect(screen.getByText("Whoop")).toBeInTheDocument();
  });

  it("handles null HRV and source gracefully", () => {
    render(
      <RecoveryTile
        data={payload({
          today_hrv: null,
          today_resting_hr: null,
          hrv_baseline_7d: null,
          hrv_trend: null,
          hrv_source: null,
        })}
      />
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText(/RHR —/)).toBeInTheDocument();
    expect(screen.queryByText("Eight Sleep")).not.toBeInTheDocument();
    expect(screen.queryByText("Whoop")).not.toBeInTheDocument();
  });
});
