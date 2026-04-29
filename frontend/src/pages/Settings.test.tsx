import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "../test/renderWithQuery";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/GoalsSection", () => ({
  default: () => <div>Goals stub</div>,
}));

vi.mock("../api/locations", () => ({
  createLocation: vi.fn(),
  deleteLocation: vi.fn(),
  listLocations: vi.fn(),
  patchLocation: vi.fn(),
  setDefaultLocation: vi.fn(),
}));

vi.mock("../hooks/useUnits", () => ({
  useUnits: () => ({ units: "metric" }),
  formatElevation: (meters: number | null | undefined) =>
    meters == null ? "—" : `${Math.round(meters)} m`,
}));

vi.mock("../api/sync", () => ({
  fetchDebugDb: vi.fn(),
  fetchSyncStatus: vi.fn(),
  triggerSync: vi.fn(),
}));

import Settings from "./Settings";
import {
  createLocation,
  deleteLocation,
  listLocations,
  patchLocation,
  setDefaultLocation,
} from "../api/locations";
import { fetchDebugDb, fetchSyncStatus } from "../api/sync";

const mockedCreateLocation = vi.mocked(createLocation);
const mockedDeleteLocation = vi.mocked(deleteLocation);
const mockedListLocations = vi.mocked(listLocations);
const mockedPatchLocation = vi.mocked(patchLocation);
const mockedSetDefaultLocation = vi.mocked(setDefaultLocation);
const mockedFetchDebugDb = vi.mocked(fetchDebugDb);
const mockedFetchSyncStatus = vi.mocked(fetchSyncStatus);

const locations = [
  {
    id: 1,
    name: "Home",
    lat: 40.0,
    lng: -105.2,
    elevation_m: 1650,
    is_default: true,
  },
  {
    id: 2,
    name: "Gym",
    lat: 39.9,
    lng: -105.1,
    elevation_m: null,
    is_default: false,
  },
];

describe("Settings", () => {
  beforeEach(() => {
    mockedListLocations.mockResolvedValue(locations);
    mockedFetchDebugDb.mockResolvedValue({
      database_url: "sqlite://test",
      sqlite_main_file: ":memory:",
      database_list: [],
      row_counts: {},
    } as never);
    mockedFetchSyncStatus.mockResolvedValue({} as never);
    vi.stubGlobal("confirm", vi.fn(() => true));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("renames, sets default, and deletes saved locations", async () => {
    mockedPatchLocation.mockResolvedValue({ ...locations[0], name: "Home Base" });
    mockedSetDefaultLocation.mockResolvedValue({
      ...locations[1],
      is_default: true,
    });
    mockedDeleteLocation.mockResolvedValue(undefined);

    renderWithQuery(<Settings />);

    await screen.findByText("Saved locations");
    expect(screen.getByText("Goals stub")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Home" }));
    const renameInput = screen.getByDisplayValue("Home");
    fireEvent.change(renameInput, { target: { value: "Home Base" } });
    fireEvent.blur(renameInput);

    await waitFor(() =>
      expect(mockedPatchLocation).toHaveBeenCalledWith(1, { name: "Home Base" })
    );

    fireEvent.click(screen.getByRole("button", { name: "Make default" }));
    await waitFor(() => expect(mockedSetDefaultLocation).toHaveBeenCalledWith(2));

    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[1]);
    await waitFor(() => expect(mockedDeleteLocation).toHaveBeenCalledWith(2));
  });

  it("creates a location through the advanced form", async () => {
    mockedCreateLocation.mockResolvedValue({
      id: 3,
      name: "Track",
      lat: 37.33,
      lng: -121.89,
      elevation_m: 25,
      is_default: false,
    });

    renderWithQuery(<Settings />);

    await screen.findByText("Saved locations");
    fireEvent.click(screen.getByRole("button", { name: "Enter coords manually" }));

    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Track" },
    });
    fireEvent.change(screen.getByPlaceholderText("Latitude (e.g. 37.7749)"), {
      target: { value: "37.33" },
    });
    fireEvent.change(screen.getByPlaceholderText("Longitude (e.g. -122.4194)"), {
      target: { value: "-121.89" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("Elevation in meters (optional)"),
      {
        target: { value: "25" },
      }
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockedCreateLocation).toHaveBeenCalledWith({
        name: "Track",
        lat: 37.33,
        lng: -121.89,
        elevation_m: 25,
      })
    );
  });
});
