import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { EnvironmentTodayPayload } from "../../api/dashboard";
import { UnitsProvider } from "../../hooks/useUnits";
import EnvironmentTile from "./EnvironmentTile";

function renderTile(data: EnvironmentTodayPayload | null) {
  return render(
    <UnitsProvider>
      <EnvironmentTile data={data} />
    </UnitsProvider>
  );
}

describe("EnvironmentTile", () => {
  it("renders empty state when data is null", () => {
    renderTile(null);
    expect(screen.getByText("Set a default location in Settings")).toBeInTheDocument();
  });

  it("renders empty state when both forecast and air_quality are null", () => {
    renderTile({ forecast: null, air_quality: null });
    expect(screen.getByText("Set a default location in Settings")).toBeInTheDocument();
  });

  it("renders temperature, conditions, hi/lo, wind, AQI, and pollen", () => {
    renderTile({
      forecast: {
        temp_c: 20,
        high_c: 24,
        low_c: 12,
        conditions: "Cloudy",
        wind_ms: 4,
      },
      air_quality: {
        us_aqi: 42,
        european_aqi: null,
        pollen: {
          alder: 5,
          birch: 60,
          grass: 30,
          mugwort: null,
          olive: null,
          ragweed: null,
        },
      },
    });
    // 20°C → 68°F
    expect(screen.getByText("68°F")).toBeInTheDocument();
    expect(screen.getByText(/Cloudy/)).toBeInTheDocument();
    expect(screen.getByText(/H 75°F \/ L 54°F/)).toBeInTheDocument();
    expect(screen.getByText(/wind/)).toBeInTheDocument();
    const aqi = screen.getByText("AQI 42");
    expect(aqi).toHaveStyle({ background: "var(--green)" });
    expect(screen.getByText(/Birch 60/)).toBeInTheDocument();
    expect(screen.getByText(/Grass 30/)).toBeInTheDocument();
  });

  it("colors AQI orange in 51-100 range and red above 100", () => {
    const { rerender } = renderTile({
      forecast: null,
      air_quality: { us_aqi: 75, european_aqi: null, pollen: null },
    });
    expect(screen.getByText("AQI 75")).toHaveStyle({ background: "var(--orange)" });

    rerender(
      <UnitsProvider>
        <EnvironmentTile
          data={{
            forecast: null,
            air_quality: { us_aqi: 160, european_aqi: null, pollen: null },
          }}
        />
      </UnitsProvider>
    );
    expect(screen.getByText("AQI 160")).toHaveStyle({ background: "var(--red)" });
  });

  it("hides pollen line when all values below threshold", () => {
    renderTile({
      forecast: {
        temp_c: 15,
        high_c: 18,
        low_c: 10,
        conditions: "Clear",
        wind_ms: 2,
      },
      air_quality: {
        us_aqi: 30,
        european_aqi: null,
        pollen: { alder: 5, birch: 8, grass: 3, mugwort: null, olive: null, ragweed: null },
      },
    });
    expect(screen.queryByText(/Pollen:/)).not.toBeInTheDocument();
  });
});
