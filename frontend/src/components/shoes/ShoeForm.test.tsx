import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/shoes", () => ({
  createShoe: vi.fn(),
  patchShoe: vi.fn(),
}));

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: "metric" }),
}));

import { renderWithQuery } from "../../test/renderWithQuery";
import ShoeForm from "./ShoeForm";
import { createShoe, patchShoe } from "../../api/shoes";

const mockedCreateShoe = vi.mocked(createShoe);
const mockedPatchShoe = vi.mocked(patchShoe);

const createdShoe = {
  id: 1,
  name: "Vaporfly",
  brand: null,
  model: null,
  shoe_type: "everyday" as const,
  status: "active" as const,
  total_usable_distance_m: null,
  purchased_on: null,
  retired_at: null,
  notes: null,
  created_at: "2026-01-10T00:00:00Z",
  updated_at: "2026-01-10T00:00:00Z",
  cumulative_distance_m: 0,
  percent_used: null,
};

describe("ShoeForm (create)", () => {
  beforeEach(() => {
    mockedCreateShoe.mockResolvedValue(createdShoe);
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("disables Save until name has at least one non-whitespace character", () => {
    renderWithQuery(<ShoeForm onSaved={vi.fn()} />);
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/Vaporfly 3 — blue/), {
      target: { value: "   " },
    });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/Vaporfly 3 — blue/), {
      target: { value: "My shoe" },
    });
    expect(save).not.toBeDisabled();
  });

  it("trims whitespace and sends optional fields as null when empty", async () => {
    const onSaved = vi.fn();
    renderWithQuery(<ShoeForm onSaved={onSaved} />);
    fireEvent.change(screen.getByPlaceholderText(/Vaporfly 3 — blue/), {
      target: { value: "  Vaporfly  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockedCreateShoe).toHaveBeenCalledTimes(1));
    expect(mockedCreateShoe).toHaveBeenCalledWith({
      name: "Vaporfly",
      brand: null,
      model: null,
      shoe_type: "everyday",
      total_usable_distance_m: null,
      purchased_on: null,
      notes: null,
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(createdShoe));
  });

  it("converts the lifespan input to meters (metric → km × 1000)", async () => {
    renderWithQuery(<ShoeForm onSaved={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/Vaporfly 3 — blue/), {
      target: { value: "Pegasus" },
    });
    fireEvent.change(screen.getByPlaceholderText(/typical: 500–800 km/), {
      target: { value: "600" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mockedCreateShoe).toHaveBeenCalledTimes(1));
    expect(mockedCreateShoe.mock.calls[0][0].total_usable_distance_m).toBe(
      600000,
    );
  });

  it("rejects a negative lifespan input client-side", () => {
    renderWithQuery(<ShoeForm onSaved={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/Vaporfly 3 — blue/), {
      target: { value: "Pegasus" },
    });
    fireEvent.change(screen.getByPlaceholderText(/typical: 500–800 km/), {
      target: { value: "-50" },
    });
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(
      screen.getByText(
        /Enter a positive number, or leave blank for no target./,
      ),
    ).toBeInTheDocument();
  });
});

describe("ShoeForm (edit)", () => {
  beforeEach(() => {
    mockedPatchShoe.mockResolvedValue({
      ...createdShoe,
      name: "Vaporfly Renamed",
    });
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("prefills all fields and PATCHes on save", async () => {
    const existing = {
      ...createdShoe,
      id: 7,
      name: "Vaporfly",
      brand: "Nike",
      model: "ZoomX",
      shoe_type: "race" as const,
      total_usable_distance_m: 400000, // 400 km
      purchased_on: "2026-01-10",
      notes: "Race-day only",
    };
    renderWithQuery(<ShoeForm shoe={existing} onSaved={vi.fn()} />);

    expect(screen.getByDisplayValue("Vaporfly")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Nike")).toBeInTheDocument();
    expect(screen.getByDisplayValue("ZoomX")).toBeInTheDocument();
    // The shoe_type <select> defaults to "race" — check value directly.
    const typeSelect = screen.getByRole("combobox") as HTMLSelectElement;
    expect(typeSelect.value).toBe("race");
    expect(screen.getByDisplayValue("400")).toBeInTheDocument(); // km
    expect(screen.getByDisplayValue("2026-01-10")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Race-day only")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(mockedPatchShoe).toHaveBeenCalledTimes(1));
    expect(mockedPatchShoe).toHaveBeenCalledWith(7, expect.objectContaining({
      name: "Vaporfly",
      brand: "Nike",
      model: "ZoomX",
      shoe_type: "race",
      total_usable_distance_m: 400000,
      purchased_on: "2026-01-10",
      notes: "Race-day only",
    }));
  });
});
