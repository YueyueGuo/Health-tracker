import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { searchLocations, type LocationSearchHit } from "../api/locations";
import { useDebouncedLocationSearch } from "./useDebouncedLocationSearch";

vi.mock("../api/locations", () => ({
  searchLocations: vi.fn(),
}));

const mockedSearchLocations = vi.mocked(searchLocations);

describe("useDebouncedLocationSearch", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not search for a blank query", () => {
    const { result } = renderHook(() => useDebouncedLocationSearch("   "));

    expect(result.current).toEqual({
      results: null,
      searching: false,
      error: null,
    });
    expect(mockedSearchLocations).not.toHaveBeenCalled();
  });

  it("debounces and returns search results", async () => {
    const hits: LocationSearchHit[] = [
      {
        name: "Boulder",
        lat: 40.01499,
        lng: -105.27055,
        elevation_m: 1624,
        country: "United States",
        admin1: "Colorado",
        admin2: null,
        population: 108250,
      },
    ];
    mockedSearchLocations.mockResolvedValueOnce(hits);

    const { result } = renderHook(() => useDebouncedLocationSearch("Boulder", 5, 0));

    await waitFor(() => expect(mockedSearchLocations).toHaveBeenCalledWith("Boulder", 5));
    await waitFor(() => expect(result.current.searching).toBe(false));
    expect(result.current.results).toEqual(hits);
    expect(result.current.error).toBeNull();
  });

  it("surfaces search errors", async () => {
    mockedSearchLocations.mockRejectedValueOnce(new Error("Search failed"));

    const { result } = renderHook(() => useDebouncedLocationSearch("Tahoe", 5, 0));

    await waitFor(() => expect(mockedSearchLocations).toHaveBeenCalledWith("Tahoe", 5));
    await waitFor(() => expect(result.current.searching).toBe(false));
    expect(result.current.error).toBe("Search failed");
    expect(result.current.results).toBeNull();
  });
});
