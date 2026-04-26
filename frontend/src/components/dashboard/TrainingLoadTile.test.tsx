import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ACWR_TOOLTIP, type TrainingTodayPayload } from "../../api/dashboard";
import TrainingLoadTile from "./TrainingLoadTile";

function payload(overrides: Partial<TrainingTodayPayload> = {}): TrainingTodayPayload {
  return {
    yesterday_stress: 78.4,
    week_to_date_load: 412.1,
    acwr: 1.12,
    acwr_band: "optimal",
    days_since_hard: 2,
    ...overrides,
  };
}

describe("TrainingLoadTile", () => {
  it("renders WTD load, yesterday stress, days-since-hard, and ACWR chip", () => {
    render(<TrainingLoadTile data={payload()} />);
    expect(screen.getByText("412")).toBeInTheDocument();
    expect(screen.getByText(/yesterday 78/)).toBeInTheDocument();
    expect(screen.getByText(/2d since hard/)).toBeInTheDocument();
    const chip = screen.getByText(/ACWR 1.12 · optimal/);
    expect(chip).toHaveAttribute("title", ACWR_TOOLTIP);
    expect(chip).toHaveStyle({ background: "var(--green)" });
  });

  it("colors caution band orange", () => {
    render(<TrainingLoadTile data={payload({ acwr: 1.4, acwr_band: "caution" })} />);
    expect(screen.getByText(/ACWR 1.40 · caution/)).toHaveStyle({
      background: "var(--orange)",
    });
  });

  it("colors elevated band red", () => {
    render(<TrainingLoadTile data={payload({ acwr: 1.7, acwr_band: "elevated" })} />);
    expect(screen.getByText(/ACWR 1.70 · elevated/)).toHaveStyle({
      background: "var(--red)",
    });
  });

  it("colors detraining band muted", () => {
    render(<TrainingLoadTile data={payload({ acwr: 0.6, acwr_band: "detraining" })} />);
    expect(screen.getByText(/ACWR 0.60 · detraining/)).toHaveStyle({
      background: "var(--text-muted)",
    });
  });

  it("hides ACWR chip when band/acwr is null", () => {
    render(<TrainingLoadTile data={payload({ acwr: null, acwr_band: null })} />);
    expect(screen.queryByText(/ACWR/)).not.toBeInTheDocument();
  });
});
