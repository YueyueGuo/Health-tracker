// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("./dashboard/MorningStatusCard", () => ({
  MorningStatusCard: () => <div>Morning status card</div>,
}));

vi.mock("./dashboard/RecommendationCardV2", () => ({
  RecommendationCardV2: () => <div>Recommendation card</div>,
}));

vi.mock("./dashboard/YesterdayActivityCard", () => ({
  YesterdayActivityCard: () => <div>Yesterday activity card</div>,
}));

import Dashboard from "./Dashboard";

describe("Dashboard", () => {
  it("renders the three home cards in order", () => {
    render(<Dashboard />);
    expect(screen.getByText("Morning status card")).toBeInTheDocument();
    expect(screen.getByText("Recommendation card")).toBeInTheDocument();
    expect(screen.getByText("Yesterday activity card")).toBeInTheDocument();
  });
});
