import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LocationSearchHit } from "../../api/locations";
import LocationSearchForm from "./LocationSearchForm";

vi.mock("../../hooks/useDebouncedLocationSearch", () => ({
  useDebouncedLocationSearch: vi.fn(),
}));

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: "metric" }),
  formatElevation: (meters: number | null | undefined) =>
    meters == null ? "—" : `${Math.round(meters)} m`,
}));

import { useDebouncedLocationSearch } from "../../hooks/useDebouncedLocationSearch";

const mockedUseDebouncedLocationSearch = vi.mocked(useDebouncedLocationSearch);

describe("LocationSearchForm", () => {
  it("completes the requireName pick flow", () => {
    const hit: LocationSearchHit = {
      name: "Boulder",
      lat: 40.01499,
      lng: -105.27055,
      elevation_m: 1624,
      country: "United States",
      admin1: "Colorado",
      admin2: null,
      population: 108250,
    };
    const onPick = vi.fn();
    mockedUseDebouncedLocationSearch.mockReturnValue({
      results: [hit],
      searching: false,
      error: null,
    });

    render(
      <LocationSearchForm
        requireName
        onCancel={vi.fn()}
        onPick={onPick}
      />
    );

    fireEvent.change(screen.getByPlaceholderText("e.g. Boulder, CO"), {
      target: { value: "Boulder" },
    });
    fireEvent.click(screen.getByRole("button", { name: /boulder, colorado, united states/i }));

    const nameInput = screen.getByPlaceholderText(
      "Name this location (e.g. Tahoe cabin)"
    );
    fireEvent.change(nameInput, { target: { value: "Trailhead" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onPick).toHaveBeenCalledWith("Trailhead", hit);
  });
});
