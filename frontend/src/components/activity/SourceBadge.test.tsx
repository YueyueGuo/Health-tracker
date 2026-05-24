import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SourceBadge from "./SourceBadge";

describe("SourceBadge", () => {
  it("renders an Apple pill for the apple source", () => {
    render(<SourceBadge source="apple" />);
    const badge = screen.getByTestId("source-badge-apple");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Apple");
    expect(badge).toHaveAttribute("aria-label", "Source: Apple Health");
  });

  it("renders a Strava pill for the strava source", () => {
    render(<SourceBadge source="strava" />);
    const badge = screen.getByTestId("source-badge-strava");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("Strava");
    expect(badge).toHaveAttribute("aria-label", "Source: Strava");
  });

  it("renders nothing when source is undefined", () => {
    const { container } = render(<SourceBadge source={undefined} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId("source-badge-apple")).not.toBeInTheDocument();
    expect(screen.queryByTestId("source-badge-strava")).not.toBeInTheDocument();
  });

  it("uses orange-tinted classes for Strava", () => {
    render(<SourceBadge source="strava" />);
    const badge = screen.getByTestId("source-badge-strava");
    expect(badge.className).toMatch(/orange/);
  });

  it("uses slate/gray-tinted classes for Apple", () => {
    render(<SourceBadge source="apple" />);
    const badge = screen.getByTestId("source-badge-apple");
    expect(badge.className).toMatch(/slate/);
  });
});
