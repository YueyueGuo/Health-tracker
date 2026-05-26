import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PhysiologyVitalsCard from "./PhysiologyVitalsCard";
import { UnitsProvider } from "../../hooks/useUnits";
import type { ProfileVitals } from "../../hooks/useProfilePreferences";

const vitals: ProfileVitals = {
  age: "32",
  weight: "175",
  height: "5'10\"",
  maxHr: "192",
  lthr: "174",
};

describe("PhysiologyVitalsCard", () => {
  it("renders the weight suffix as lb in imperial mode (the default)", () => {
    window.localStorage.removeItem("ht.units");
    render(
      <UnitsProvider>
        <PhysiologyVitalsCard vitals={vitals} onChange={() => {}} />
      </UnitsProvider>
    );
    expect(screen.getByText("lb")).toBeInTheDocument();
    expect(screen.queryByText("kg")).not.toBeInTheDocument();
  });

  it("renders the weight suffix as kg when the metric system is active", () => {
    window.localStorage.setItem("ht.units", "metric");
    render(
      <UnitsProvider>
        <PhysiologyVitalsCard vitals={vitals} onChange={() => {}} />
      </UnitsProvider>
    );
    expect(screen.getByText("kg")).toBeInTheDocument();
    expect(screen.queryByText("lb")).not.toBeInTheDocument();
    window.localStorage.removeItem("ht.units");
  });
});
