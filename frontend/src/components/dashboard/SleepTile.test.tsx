import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SleepTodayPayload } from "../../api/dashboard";
import SleepTile from "./SleepTile";

function payload(overrides: Partial<SleepTodayPayload> = {}): SleepTodayPayload {
  return {
    last_night_score: 89,
    last_night_duration_min: 500,
    last_night_deep_min: 92,
    last_night_rem_min: 118,
    last_night_date: "2026-04-25",
    ...overrides,
  };
}

describe("SleepTile", () => {
  it("renders score, formatted duration, and deep/REM breakdown", () => {
    render(<SleepTile data={payload()} />);
    expect(screen.getByText("89")).toBeInTheDocument();
    expect(screen.getByText("8h 20m")).toBeInTheDocument();
    expect(
      screen.getByText((_, node) => node?.textContent === "Deep 1h 32m · REM 1h 58m")
    ).toBeInTheDocument();
  });

  it("color-codes score by threshold (≥80 green, ≥60 orange, else red)", () => {
    const { rerender } = render(<SleepTile data={payload({ last_night_score: 80 })} />);
    expect(screen.getByText("80")).toHaveStyle({ color: "var(--green)" });

    rerender(<SleepTile data={payload({ last_night_score: 65 })} />);
    expect(screen.getByText("65")).toHaveStyle({ color: "var(--orange)" });

    rerender(<SleepTile data={payload({ last_night_score: 40 })} />);
    expect(screen.getByText("40")).toHaveStyle({ color: "var(--red)" });
  });

  it("renders empty state when no score", () => {
    render(
      <SleepTile
        data={payload({
          last_night_score: null,
          last_night_duration_min: null,
          last_night_deep_min: null,
          last_night_rem_min: null,
        })}
      />
    );
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
