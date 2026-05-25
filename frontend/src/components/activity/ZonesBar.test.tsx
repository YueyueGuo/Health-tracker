import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ZonesBar from "./ZonesBar";
import type { ZoneDistribution } from "../../api/activities";

const HR_BUCKETS = [
  { min: 0, max: 120, time: 60 },
  { min: 121, max: 140, time: 240 },
  { min: 141, max: 160, time: 480 },
  { min: 161, max: 180, time: 120 },
  { min: 181, max: -1, time: 0 },
];

describe("ZonesBar", () => {
  it("renders the synthetic caption when HR zones report sensor_based=false", () => {
    const zones: ZoneDistribution[] = [
      {
        type: "heartrate",
        distribution_buckets: HR_BUCKETS,
        sensor_based: false,
      },
    ];
    render(<ZonesBar zones={zones} />);
    expect(screen.getByText("Time in HR Zones")).toBeInTheDocument();
    expect(
      screen.getByText("Computed from raw HR samples")
    ).toBeInTheDocument();
  });

  it("does not render the synthetic caption when sensor_based is true", () => {
    const zones: ZoneDistribution[] = [
      {
        type: "heartrate",
        distribution_buckets: HR_BUCKETS,
        sensor_based: true,
      },
    ];
    render(<ZonesBar zones={zones} />);
    expect(screen.getByText("Time in HR Zones")).toBeInTheDocument();
    expect(
      screen.queryByText("Computed from raw HR samples")
    ).not.toBeInTheDocument();
  });

  it("does not render the synthetic caption when sensor_based is omitted", () => {
    const zones: ZoneDistribution[] = [
      {
        type: "heartrate",
        distribution_buckets: HR_BUCKETS,
      },
    ];
    render(<ZonesBar zones={zones} />);
    expect(
      screen.queryByText("Computed from raw HR samples")
    ).not.toBeInTheDocument();
  });

  it("does not render the synthetic caption on non-HR zone cards", () => {
    const zones: ZoneDistribution[] = [
      {
        type: "power",
        distribution_buckets: [
          { min: 0, max: 120, time: 300 },
          { min: 121, max: 180, time: 600 },
        ],
        // sensor_based=false here should not surface a caption — that copy
        // only applies to the HR card.
        sensor_based: false,
      },
    ];
    render(<ZonesBar zones={zones} />);
    expect(screen.getByText("Time in Power Zones")).toBeInTheDocument();
    expect(
      screen.queryByText("Computed from raw HR samples")
    ).not.toBeInTheDocument();
  });

  it("renders nothing when all buckets are empty", () => {
    const zones: ZoneDistribution[] = [
      {
        type: "heartrate",
        distribution_buckets: HR_BUCKETS.map((b) => ({ ...b, time: 0 })),
        sensor_based: false,
      },
    ];
    const { container } = render(<ZonesBar zones={zones} />);
    expect(container).toBeEmptyDOMElement();
  });
});
