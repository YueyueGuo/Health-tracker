import { fireEvent, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { renderWithQuery } from "../test/renderWithQuery";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/profile", () => ({
  fetchProfile: vi.fn(),
  patchProfile: vi.fn(),
}));

vi.mock("../api/sync", () => ({
  fetchSyncStatus: vi.fn(),
  fetchDebugDb: vi.fn(),
  triggerSync: vi.fn(),
}));

vi.mock("../api/shoes", () => ({
  listShoes: vi.fn(),
}));

vi.mock("../components/GoalsSection", () => ({
  default: () => <div>Goals stub</div>,
}));

vi.mock("../components/settings/LocationSettingsSection", () => ({
  default: () => <div>Locations stub</div>,
}));

vi.mock("../components/settings/SyncSection", () => ({
  default: () => <div>Sync stub</div>,
}));

import Settings from "./Settings";
import { UnitsProvider } from "../hooks/useUnits";
import { DEFAULT_PROFILE_PREFERENCES } from "../hooks/useProfilePreferences";
import { fetchProfile, patchProfile } from "../api/profile";
import { fetchSyncStatus } from "../api/sync";
import { listShoes } from "../api/shoes";

const mockedFetchProfile = vi.mocked(fetchProfile);
const mockedPatchProfile = vi.mocked(patchProfile);
const mockedFetchSyncStatus = vi.mocked(fetchSyncStatus);
const mockedListShoes = vi.mocked(listShoes);

function renderSettings() {
  return renderWithQuery(
    <MemoryRouter initialEntries={["/settings"]}>
      <UnitsProvider>
        <Settings />
      </UnitsProvider>
    </MemoryRouter>
  );
}

describe("Settings", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockedFetchProfile.mockResolvedValue({ ...DEFAULT_PROFILE_PREFERENCES });
    mockedPatchProfile.mockImplementation(async (prefs) => prefs);
    mockedFetchSyncStatus.mockResolvedValue({} as never);
    mockedListShoes.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("renders the four main cards under the Settings header", async () => {
    renderSettings();

    expect(
      screen.getByRole("heading", { name: "Settings", level: 1 })
    ).toBeInTheDocument();

    await waitFor(() =>
      expect(screen.queryByText("Loading account…")).not.toBeInTheDocument()
    );

    expect(
      screen.getByRole("heading", { name: "Account" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Preferences" })
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Gear" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Data Sources" })
    ).toBeInTheDocument();
  });

  it("keeps the Advanced section collapsed by default and expands on click", async () => {
    renderSettings();

    await screen.findByRole("heading", { name: "Account" });

    expect(screen.queryByText("Goals stub")).not.toBeInTheDocument();
    expect(screen.queryByText("Locations stub")).not.toBeInTheDocument();
    expect(screen.queryByText("Sync stub")).not.toBeInTheDocument();

    const trigger = screen.getByRole("button", { name: /Advanced/ });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Goals stub")).toBeInTheDocument();
    expect(screen.getByText("Locations stub")).toBeInTheDocument();
    expect(screen.getByText("Sync stub")).toBeInTheDocument();
  });

  it("persists name edits through patchProfile", async () => {
    renderSettings();

    await waitFor(() => expect(mockedFetchProfile).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByText("Loading account…")).not.toBeInTheDocument()
    );

    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Yueyue" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save account" }));

    await waitFor(() =>
      expect(mockedPatchProfile).toHaveBeenCalledWith(
        expect.objectContaining({ displayName: "Yueyue" })
      )
    );
  });

  it("toggling Metric updates the ht.units localStorage entry", async () => {
    renderSettings();

    await screen.findByRole("heading", { name: "Preferences" });

    fireEvent.click(screen.getByRole("button", { name: "Metric" }));

    await waitFor(() =>
      expect(window.localStorage.getItem("ht.units")).toBe("metric")
    );
  });

  it("accepts a YYYY-MM-DD value in the date-of-birth input", async () => {
    renderSettings();

    await waitFor(() =>
      expect(screen.queryByText("Loading account…")).not.toBeInTheDocument()
    );

    const dob = screen.getByLabelText("Date of birth") as HTMLInputElement;
    fireEvent.change(dob, { target: { value: "1993-10-12" } });
    expect(dob.value).toBe("1993-10-12");

    fireEvent.click(screen.getByRole("button", { name: "Save account" }));
    await waitFor(() =>
      expect(mockedPatchProfile).toHaveBeenCalledWith(
        expect.objectContaining({ dateOfBirth: "1993-10-12" })
      )
    );
  });

  it("links the Shoes gear row to /shoes", async () => {
    renderSettings();

    const link = await screen.findByRole("link", { name: /Shoes/ });
    expect(link.getAttribute("href")).toBe("/shoes");
  });
});
