import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../api/activities", () => ({
  fetchActivities: () =>
    Promise.resolve([
      {
        id: 1,
        strava_id: 1001,
        name: "Morning Ride",
        sport_type: "Ride",
        start_date: "2026-04-25T13:00:00Z",
        start_date_local: "2026-04-25T06:30:00",
        elapsed_time: 5520,
        moving_time: 5520,
        distance: 45700,
        total_elevation: 200,
        average_hr: 142,
        max_hr: 170,
        average_speed: 8.0,
        max_speed: 12.0,
        average_power: null,
        max_power: null,
        weighted_avg_power: null,
        average_cadence: null,
        calories: null,
        kilojoules: null,
        suffer_score: 82,
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
      },
    ]),
}));

vi.mock("../api/sleep", () => ({
  fetchSleepSessions: () =>
    Promise.resolve([
      {
        id: 1,
        source: "eight_sleep",
        date: "2026-04-25",
        bed_time: "2026-04-24T23:00:00",
        wake_time: "2026-04-25T06:00:00",
        total_duration: 462,
        deep_sleep: 90,
        rem_sleep: 110,
        light_sleep: 250,
        awake_time: 12,
        sleep_score: 85,
        sleep_fitness_score: 78,
        avg_hr: 56,
        hrv: 52,
        respiratory_rate: 14,
        bed_temp: null,
        tnt_count: 5,
        latency: 600,
      },
      {
        id: 2,
        source: "eight_sleep",
        date: "2026-04-24",
        bed_time: "2026-04-23T23:30:00",
        wake_time: "2026-04-24T05:00:00",
        total_duration: 312,
        deep_sleep: 40,
        rem_sleep: 70,
        light_sleep: 200,
        awake_time: 30,
        sleep_score: 55,
        sleep_fitness_score: 42,
        avg_hr: 60,
        hrv: 38,
        respiratory_rate: 14,
        bed_temp: null,
        tnt_count: 12,
        latency: 1500,
      },
    ]),
}));

vi.mock("../api/strength", () => ({
  fetchStrengthSessions: () =>
    Promise.resolve([
      {
        date: "2026-04-24",
        exercise_count: 4,
        total_sets: 12,
        total_volume_kg: 5630,
        activity_id: null,
      },
    ]),
}));

import History from "./History";

function renderWithRouter() {
  return render(
    <MemoryRouter initialEntries={["/history"]}>
      <Routes>
        <Route path="/history" element={<History />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("History page", () => {
  it("renders merged events and the filter row", async () => {
    renderWithRouter();
    expect(screen.getByRole("heading", { name: "History" })).toBeInTheDocument();
    expect(await screen.findByText("Morning Ride")).toBeInTheDocument();
    expect(screen.getAllByText("Sleep & Recovery").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Strength Session")).toBeInTheDocument();
  });

  it('filter pill "Health & Sleep" hides workouts', async () => {
    renderWithRouter();
    await screen.findByText("Morning Ride");
    fireEvent.click(screen.getByRole("button", { name: "Health & Sleep" }));
    await waitFor(() => {
      expect(screen.queryByText("Morning Ride")).not.toBeInTheDocument();
      expect(screen.queryByText("Strength Session")).not.toBeInTheDocument();
      expect(screen.getAllByText("Sleep & Recovery").length).toBeGreaterThanOrEqual(1);
    });
  });

  it('filter pill "Strength" shows only strength sessions', async () => {
    renderWithRouter();
    await screen.findByText("Morning Ride");
    fireEvent.click(screen.getByRole("button", { name: "Strength" }));
    await waitFor(() => {
      expect(screen.queryByText("Morning Ride")).not.toBeInTheDocument();
      expect(screen.queryByText("Sleep & Recovery")).not.toBeInTheDocument();
      expect(screen.getByText("Strength Session")).toBeInTheDocument();
    });
  });
});
