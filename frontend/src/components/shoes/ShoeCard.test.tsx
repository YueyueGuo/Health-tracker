import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Shoe } from "../../api/shoes";

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: "metric" }),
}));

import ShoeCard from "./ShoeCard";

function makeShoe(overrides: Partial<Shoe> = {}): Shoe {
  return {
    id: 1,
    name: "Vaporfly 3",
    brand: "Nike",
    model: "ZoomX",
    shoe_type: "race",
    status: "active",
    total_usable_distance_m: 800000,
    purchased_on: "2026-01-10",
    retired_at: null,
    notes: null,
    created_at: "2026-01-10T00:00:00Z",
    updated_at: "2026-01-10T00:00:00Z",
    cumulative_distance_m: 200000,
    percent_used: 25,
    ...overrides,
  };
}

function renderCard(shoe: Shoe) {
  return render(
    <MemoryRouter>
      <ShoeCard shoe={shoe} />
    </MemoryRouter>,
  );
}

describe("ShoeCard", () => {
  it("renders name + brand + model when present", () => {
    renderCard(makeShoe());
    expect(screen.getByText("Vaporfly 3")).toBeInTheDocument();
    expect(screen.getByText("Nike · ZoomX")).toBeInTheDocument();
  });

  it("omits the brand/model subline when both are null", () => {
    renderCard(makeShoe({ brand: null, model: null }));
    expect(screen.queryByText(/·/)).not.toBeInTheDocument();
  });

  it("renders 'no target set' when total_usable_distance_m is null", () => {
    renderCard(makeShoe({ total_usable_distance_m: null, percent_used: null }));
    expect(screen.getByText(/no target set/)).toBeInTheDocument();
  });

  it("renders the amber chip when percent_used >= 80", () => {
    renderCard(makeShoe({ percent_used: 85 }));
    expect(screen.getByTestId("approaching-eol-chip")).toBeInTheDocument();
  });

  it("renders the red chip when percent_used >= 100", () => {
    renderCard(makeShoe({ percent_used: 110 }));
    expect(screen.getByTestId("overdue-chip")).toBeInTheDocument();
  });

  it("respects the metric unit system", () => {
    renderCard(makeShoe({ cumulative_distance_m: 200000 }));
    // 200000 m = 200 km
    expect(screen.getByText(/200 km/)).toBeInTheDocument();
  });
});
