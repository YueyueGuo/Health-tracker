import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/shoes", () => ({
  listShoes: vi.fn(),
}));

import { renderWithQuery } from "../../test/renderWithQuery";
import ShoesSettingsCard from "./ShoesSettingsCard";
import { listShoes } from "../../api/shoes";

const mockedListShoes = vi.mocked(listShoes);

describe("ShoesSettingsCard", () => {
  beforeEach(() => {
    mockedListShoes.mockResolvedValue([]);
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders a Manage shoes link pointing to /shoes", async () => {
    renderWithQuery(
      <MemoryRouter>
        <ShoesSettingsCard />
      </MemoryRouter>,
    );
    const link = await screen.findByRole("link", { name: "Manage shoes" });
    expect(link.getAttribute("href")).toBe("/shoes");
  });

  it("renders a 'No shoes yet' summary when there are no active shoes", async () => {
    renderWithQuery(
      <MemoryRouter>
        <ShoesSettingsCard />
      </MemoryRouter>,
    );
    await screen.findByText("No shoes yet");
  });

  it("highlights the shoe with the highest percent_used in the summary line", async () => {
    mockedListShoes.mockResolvedValue([
      {
        id: 1,
        name: "Pegasus",
        brand: null,
        model: null,
        shoe_type: "everyday",
        status: "active",
        total_usable_distance_m: 800000,
        purchased_on: null,
        retired_at: null,
        notes: null,
        created_at: "",
        updated_at: "",
        cumulative_distance_m: 400000,
        percent_used: 50,
      },
      {
        id: 2,
        name: "Vaporfly",
        brand: null,
        model: null,
        shoe_type: "race",
        status: "active",
        total_usable_distance_m: 400000,
        purchased_on: null,
        retired_at: null,
        notes: null,
        created_at: "",
        updated_at: "",
        cumulative_distance_m: 320000,
        percent_used: 80,
      },
    ]);
    renderWithQuery(
      <MemoryRouter>
        <ShoesSettingsCard />
      </MemoryRouter>,
    );
    await screen.findByText("2 active · Vaporfly at 80%");
  });
});
