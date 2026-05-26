import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/shoes", () => ({
  listShoes: vi.fn(),
  createShoe: vi.fn(),
  patchShoe: vi.fn(),
  retireShoe: vi.fn(),
  unretireShoe: vi.fn(),
}));

vi.mock("../hooks/useUnits", () => ({
  useUnits: () => ({ units: "metric" }),
}));

import { renderWithQuery } from "../test/renderWithQuery";
import Shoes from "./Shoes";
import { createShoe, listShoes, type Shoe } from "../api/shoes";

const mockedListShoes = vi.mocked(listShoes);
const mockedCreateShoe = vi.mocked(createShoe);

function shoe(over: Partial<Shoe> = {}): Shoe {
  return {
    id: 1,
    name: "Vaporfly",
    brand: "Nike",
    model: "ZoomX",
    shoe_type: "race",
    status: "active",
    total_usable_distance_m: 400000,
    purchased_on: null,
    retired_at: null,
    notes: null,
    created_at: "2026-01-10T00:00:00Z",
    updated_at: "2026-01-10T00:00:00Z",
    cumulative_distance_m: 100000,
    percent_used: 25,
    ...over,
  };
}

function renderPage() {
  return renderWithQuery(
    <MemoryRouter>
      <Shoes />
    </MemoryRouter>,
  );
}

describe("Shoes page", () => {
  beforeEach(() => {
    mockedListShoes.mockResolvedValue([]);
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the empty state with an 'Add your first shoe' CTA when listShoes is []", async () => {
    renderPage();
    await screen.findByText("No shoes yet");
    expect(
      screen.getByRole("button", { name: "Add your first shoe" }),
    ).toBeInTheDocument();
  });

  it("renders one card per active shoe", async () => {
    mockedListShoes.mockResolvedValue([
      shoe(),
      shoe({ id: 2, name: "Pegasus", shoe_type: "everyday" }),
    ]);
    renderPage();
    await screen.findByText("Vaporfly");
    expect(screen.getByText("Pegasus")).toBeInTheDocument();
    expect(screen.getAllByTestId("shoe-card")).toHaveLength(2);
  });

  it("re-fetches with status=retired when the toggle is clicked", async () => {
    mockedListShoes.mockResolvedValue([shoe()]);
    renderPage();
    await screen.findByText("Vaporfly");
    mockedListShoes.mockResolvedValue([
      shoe({ id: 99, name: "Old Pegasus", status: "retired", retired_at: "2025-10-10T00:00:00Z" }),
    ]);
    fireEvent.click(screen.getByRole("tab", { name: "retired" }));
    await waitFor(() =>
      expect(mockedListShoes).toHaveBeenCalledWith("retired"),
    );
    await screen.findByText("Old Pegasus");
  });

  it("opens the form modal when Add shoe is clicked", async () => {
    renderPage();
    await screen.findByText("No shoes yet");
    fireEvent.click(screen.getByTestId("add-shoe-button"));
    expect(screen.getByTestId("shoe-form-modal")).toBeInTheDocument();
  });

  it("creates a shoe via the modal and shows the new card", async () => {
    mockedListShoes.mockResolvedValueOnce([]);
    mockedCreateShoe.mockResolvedValue(shoe({ id: 5, name: "Brand new" }));
    renderPage();
    await screen.findByText("No shoes yet");
    fireEvent.click(screen.getByTestId("add-first-shoe"));

    const modal = screen.getByTestId("shoe-form-modal");
    fireEvent.change(within(modal).getByPlaceholderText(/Vaporfly 3 — blue/), {
      target: { value: "Brand new" },
    });

    // After save, the list refetches.
    mockedListShoes.mockResolvedValue([shoe({ id: 5, name: "Brand new" })]);
    fireEvent.click(within(modal).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockedCreateShoe).toHaveBeenCalledWith(
        expect.objectContaining({ name: "Brand new" }),
      ),
    );
    await screen.findByText("Brand new");
  });

  it("renders the amber warning chip on cards with percent_used >= 80", async () => {
    mockedListShoes.mockResolvedValue([shoe({ percent_used: 85 })]);
    renderPage();
    await screen.findByText("Vaporfly");
    expect(screen.getByTestId("approaching-eol-chip")).toBeInTheDocument();
  });

  it("renders the red overdue chip on cards with percent_used >= 100", async () => {
    mockedListShoes.mockResolvedValue([shoe({ percent_used: 110 })]);
    renderPage();
    await screen.findByText("Vaporfly");
    expect(screen.getByTestId("overdue-chip")).toBeInTheDocument();
  });

  it("links each card to /shoes/:id", async () => {
    mockedListShoes.mockResolvedValue([shoe()]);
    renderPage();
    const link = await screen.findByRole("link", { name: "Vaporfly" });
    expect(link.getAttribute("href")).toBe("/shoes/1");
  });
});
