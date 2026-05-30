// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "../test/renderWithQuery";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { HistoryFeedPage } from "../api/dashboard";

const fetchHistoryFeed = vi.fn<(cursor?: string, limit?: number) => Promise<HistoryFeedPage>>();

vi.mock("../api/dashboard", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/dashboard")>()),
  fetchHistoryFeed: (cursor?: string, limit?: number) =>
    fetchHistoryFeed(cursor, limit),
}));

import History from "./History";

// --- IntersectionObserver mock ----------------------------------------------
// jsdom has no IntersectionObserver. Capture observed nodes and the callback so
// tests can manually drive an intersection.
type IOCallback = (entries: Array<{ isIntersecting: boolean }>) => void;
let observerCallback: IOCallback | null = null;
let observedCount = 0;

class MockIntersectionObserver {
  callback: IOCallback;
  constructor(cb: IOCallback) {
    this.callback = cb;
    observerCallback = cb;
  }
  observe() {
    observedCount += 1;
  }
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}

function triggerIntersection() {
  observerCallback?.([{ isIntersecting: true }]);
}

beforeEach(() => {
  observerCallback = null;
  observedCount = 0;
  fetchHistoryFeed.mockReset();
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// --- fixtures ----------------------------------------------------------------
function activity(
  id: number,
  name: string,
  start_date: string,
  sport_type = "Run",
): HistoryFeedPage["activities"][number] {
  return {
    id,
    strava_id: 1000 + id,
    name,
    sport_type,
    start_date,
    start_date_local: start_date,
    elapsed_time: 3600,
    moving_time: 3600,
    distance: 10000,
    total_elevation: 20,
    average_hr: 150,
    max_hr: 180,
    average_speed: 3.5,
    max_speed: 6.0,
    average_power: null,
    max_power: null,
    weighted_avg_power: null,
    average_cadence: null,
    calories: null,
    kilojoules: null,
    suffer_score: 80,
    device_watts: null,
    workout_type: null,
    available_zones: null,
    enrichment_status: "complete",
    enriched_at: null,
    classification_type: "endurance",
    classification_flags: null,
    classified_at: null,
    weather_enriched: false,
    elev_high_m: null,
    elev_low_m: null,
    base_elevation_m: null,
    elevation_enriched: false,
    location_id: null,
    start_lat: null,
    start_lng: null,
    rpe: null,
    user_notes: null,
    rated_at: null,
    source: "strava",
  } as HistoryFeedPage["activities"][number];
}

function page(
  activities: HistoryFeedPage["activities"],
  next_cursor: string | null,
  has_more: boolean,
): HistoryFeedPage {
  return { activities, sleep: [], strength: [], next_cursor, has_more };
}

function renderWithRouter() {
  return renderWithQuery(
    <MemoryRouter initialEntries={["/history"]}>
      <Routes>
        <Route path="/history" element={<History />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("History page (infinite scroll)", () => {
  it("appends rows when the sentinel intersects", async () => {
    fetchHistoryFeed.mockImplementation((cursor?: string) => {
      if (cursor === undefined) {
        return Promise.resolve(
          page([activity(1, "First Run", "2026-04-25T12:00:00Z")], "c1", true),
        );
      }
      return Promise.resolve(
        page([activity(2, "Second Run", "2026-04-20T12:00:00Z")], null, false),
      );
    });

    renderWithRouter();
    expect(await screen.findByText("First Run")).toBeInTheDocument();
    expect(screen.queryByText("Second Run")).not.toBeInTheDocument();
    expect(observedCount).toBeGreaterThan(0);

    triggerIntersection();

    expect(await screen.findByText("Second Run")).toBeInTheDocument();
    expect(screen.getByText("First Run")).toBeInTheDocument();
    expect(fetchHistoryFeed).toHaveBeenCalledWith("c1", undefined);
  });

  it("renders an event present in two pages only once (dedupe)", async () => {
    fetchHistoryFeed.mockImplementation((cursor?: string) => {
      if (cursor === undefined) {
        return Promise.resolve(
          page([activity(1, "Overlap Run", "2026-04-25T12:00:00Z")], "c1", true),
        );
      }
      // Same id 1 reappears at the page boundary plus a new id.
      return Promise.resolve(
        page(
          [
            activity(1, "Overlap Run", "2026-04-25T12:00:00Z"),
            activity(2, "Older Run", "2026-04-20T12:00:00Z"),
          ],
          null,
          false,
        ),
      );
    });

    renderWithRouter();
    await screen.findByText("Overlap Run");

    triggerIntersection();

    await screen.findByText("Older Run");
    expect(screen.getAllByText("Overlap Run")).toHaveLength(1);
  });

  it("shows the end marker and fires no further fetch when has_more is false", async () => {
    fetchHistoryFeed.mockResolvedValue(
      page([activity(1, "Only Run", "2026-04-25T12:00:00Z")], null, false),
    );

    renderWithRouter();
    await screen.findByText("Only Run");
    expect(await screen.findByText(/all caught up/i)).toBeInTheDocument();

    expect(fetchHistoryFeed).toHaveBeenCalledTimes(1);
    triggerIntersection();
    // No additional fetch since there is no next page.
    await waitFor(() => expect(fetchHistoryFeed).toHaveBeenCalledTimes(1));
  });

  it("does not render the time-range select", async () => {
    fetchHistoryFeed.mockResolvedValue(
      page([activity(1, "Only Run", "2026-04-25T12:00:00Z")], null, false),
    );

    renderWithRouter();
    await screen.findByText("Only Run");
    expect(
      screen.queryByRole("combobox", { name: "Time range" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("30d")).not.toBeInTheDocument();
  });
});
