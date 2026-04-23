import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LocationPicker from "./LocationPicker";

vi.mock("../api/locations", () => ({
  attachLocationToActivity: vi.fn(),
  createLocation: vi.fn(),
  detachLocationFromActivity: vi.fn(),
  listLocations: vi.fn(),
}));

vi.mock("../hooks/useUnits", () => ({
  useUnits: () => ({ units: "metric" }),
  formatElevation: (meters: number | null | undefined) =>
    meters == null ? "—" : `${Math.round(meters)} m`,
}));

vi.mock("./location/LocationSearchForm", () => ({
  default: ({
    onPick,
    onCancel,
  }: {
    onPick: (name: string, hit: {
      lat: number;
      lng: number;
      elevation_m: number | null;
    }) => void;
    onCancel: () => void;
  }) => (
    <div>
      <button
        onClick={() =>
          onPick("Trailhead", { lat: 39.7, lng: -105.0, elevation_m: 1800 })
        }
      >
        Mock search pick
      </button>
      <button onClick={onCancel}>Mock search cancel</button>
    </div>
  ),
}));

vi.mock("./location/GpsLocationForm", () => ({
  default: ({
    onPick,
    onCancel,
  }: {
    onPick: (name: string, lat: number, lng: number) => void;
    onCancel: () => void;
  }) => (
    <div>
      <button onClick={() => onPick("Home gym", 39.7392, -104.9903)}>
        Mock gps pick
      </button>
      <button onClick={onCancel}>Mock gps cancel</button>
    </div>
  ),
}));

import {
  attachLocationToActivity,
  createLocation,
  detachLocationFromActivity,
  listLocations,
} from "../api/locations";

const mockedAttachLocationToActivity = vi.mocked(attachLocationToActivity);
const mockedCreateLocation = vi.mocked(createLocation);
const mockedDetachLocationFromActivity = vi.mocked(detachLocationFromActivity);
const mockedListLocations = vi.mocked(listLocations);

describe("LocationPicker", () => {
  beforeEach(() => {
    mockedListLocations.mockResolvedValue([
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
    ]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("attaches a saved location", async () => {
    mockedAttachLocationToActivity.mockResolvedValue({
      activity_id: 7,
      location_id: 1,
      base_elevation_m: 1650,
    });
    const onChange = vi.fn();

    render(
      <LocationPicker activityId={7} currentLocationId={null} onChange={onChange} />
    );

    await screen.findByRole("button", { name: "Pick a saved place" });
    fireEvent.click(screen.getByRole("button", { name: "Pick a saved place" }));
    fireEvent.click(screen.getByRole("button", { name: /home/i }));

    await waitFor(() =>
      expect(mockedAttachLocationToActivity).toHaveBeenCalledWith(7, 1)
    );
    expect(onChange).toHaveBeenCalled();
  });

  it("creates and attaches a location from search", async () => {
    mockedCreateLocation.mockResolvedValue({
      id: 9,
      name: "Trailhead",
      lat: 39.7,
      lng: -105.0,
      elevation_m: 1800,
      is_default: false,
    });
    mockedAttachLocationToActivity.mockResolvedValue({
      activity_id: 7,
      location_id: 9,
      base_elevation_m: 1800,
    });

    const onChange = vi.fn();
    render(
      <LocationPicker activityId={7} currentLocationId={null} onChange={onChange} />
    );

    await screen.findByRole("button", { name: "Search by name" });
    fireEvent.click(screen.getByRole("button", { name: "Search by name" }));
    fireEvent.click(screen.getByRole("button", { name: "Mock search pick" }));

    await waitFor(() =>
      expect(mockedCreateLocation).toHaveBeenCalledWith({
        name: "Trailhead",
        lat: 39.7,
        lng: -105.0,
        elevation_m: 1800,
      })
    );
    expect(mockedAttachLocationToActivity).toHaveBeenCalledWith(7, 9);
    expect(onChange).toHaveBeenCalled();
  });

  it("clears the current location", async () => {
    mockedDetachLocationFromActivity.mockResolvedValue(undefined);
    const onChange = vi.fn();

    render(
      <LocationPicker activityId={7} currentLocationId={1} onChange={onChange} />
    );

    await screen.findByText("Home");
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    await waitFor(() =>
      expect(mockedDetachLocationFromActivity).toHaveBeenCalledWith(7)
    );
    expect(onChange).toHaveBeenCalled();
  });
});
