import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

vi.mock("../api/sync", () => ({
  fetchSyncStatus: vi.fn(),
}));
vi.mock("../api/profile", () => ({
  fetchProfile: vi.fn(),
  patchProfile: vi.fn(),
}));

import Profile from "./Profile";
import {
  DEFAULT_PROFILE_PREFERENCES,
  PROFILE_PREFERENCES_STORAGE_KEY,
  type ProfilePreferences,
} from "../hooks/useProfilePreferences";
import { fetchProfile, patchProfile } from "../api/profile";
import { fetchSyncStatus } from "../api/sync";

const mockedFetchSyncStatus = vi.mocked(fetchSyncStatus);
const mockedFetchProfile = vi.mocked(fetchProfile);
const mockedPatchProfile = vi.mocked(patchProfile);

function renderProfile() {
  return render(
    <MemoryRouter initialEntries={["/profile"]}>
      <Profile />
    </MemoryRouter>
  );
}

describe("Profile", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockedFetchProfile.mockResolvedValue(DEFAULT_PROFILE_PREFERENCES);
    mockedPatchProfile.mockImplementation(async (prefs) => prefs);
    mockedFetchSyncStatus.mockResolvedValue({
      strava: {
        status: "success",
        last_sync: "2026-04-28T12:00:00",
        records_synced: 12,
      },
      eight_sleep: { status: "never", last_sync: null },
      whoop: { status: "error", error: "bad token" },
      weather: { status: "success", last_sync: null },
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("renders the mockup sections with honest data-source statuses", async () => {
    renderProfile();

    await waitFor(() =>
      expect(screen.queryByText("Loading profile...")).not.toBeInTheDocument()
    );

    expect(screen.getByRole("heading", { name: "Profile" })).toBeInTheDocument();
    expect(screen.getByText("AI Coaching Directives")).toBeInTheDocument();
    expect(screen.getByText("Physiology & Vitals")).toBeInTheDocument();
    expect(screen.getByText("Data Sources")).toBeInTheDocument();

    expect(await screen.findByText("Needs setup")).toBeInTheDocument();
    expect(screen.getAllByText("Connected", { selector: "span" })).toHaveLength(2);
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(screen.getAllByText("Coming soon")).toHaveLength(2);
  });

  it("persists profile updates via PATCH /api/profile", async () => {
    renderProfile();

    await waitFor(() => expect(mockedFetchProfile).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByText("Loading profile...")).not.toBeInTheDocument()
    );

    fireEvent.change(screen.getByLabelText("Primary Focus"), {
      target: { value: "General Fitness" },
    });
    fireEvent.change(screen.getByLabelText("Weight"), {
      target: { value: "180" },
    });
    fireEvent.click(screen.getByRole("button", { name: "None" }));
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));

    await waitFor(() => expect(mockedPatchProfile).toHaveBeenCalled());
    expect(mockedPatchProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        focus: "General Fitness",
        vitals: expect.objectContaining({ weight: "180" }),
        limitations: ["None"],
      })
    );

    expect(screen.getAllByText(/^Saved /).length).toBeGreaterThan(0);

    const stored = JSON.parse(
      window.localStorage.getItem(PROFILE_PREFERENCES_STORAGE_KEY) ?? "{}"
    ) as ProfilePreferences;
    expect(stored.focus).toBe("General Fitness");
    expect(stored.vitals.weight).toBe("180");
    expect(stored.limitations).toEqual(["None"]);
  });

  it("edits and saves profile identity fields", async () => {
    renderProfile();

    await waitFor(() => expect(mockedFetchProfile).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByText("Loading profile...")).not.toBeInTheDocument()
    );

    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Yueyue" },
    });
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "yueyue@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save identity" }));

    await waitFor(() =>
      expect(mockedPatchProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          displayName: "Yueyue",
          email: "yueyue@example.com",
        })
      )
    );

    const stored = JSON.parse(
      window.localStorage.getItem(PROFILE_PREFERENCES_STORAGE_KEY) ?? "{}"
    ) as ProfilePreferences;
    expect(stored.displayName).toBe("Yueyue");
    expect(stored.email).toBe("yueyue@example.com");
  });
});
