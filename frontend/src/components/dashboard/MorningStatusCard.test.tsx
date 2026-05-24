// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "../../test/renderWithQuery";

const navigateMock = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useOutletContext: () => ({
      dateStr: "2026-05-22",
      isToday: true,
    }),
  };
});

vi.mock("../../api/sleep", () => ({
  fetchLatestSleep: vi.fn(() =>
    Promise.resolve({
      id: 1,
      source: "eight_sleep",
      date: "2026-05-22",
      bed_time: "2026-05-21T23:00:00",
      wake_time: "2026-05-22T06:30:00",
      total_duration: 450,
      deep_sleep: 90,
      rem_sleep: 100,
      light_sleep: 240,
      awake_time: 20,
      sleep_score: 84,
      sleep_fitness_score: null,
      avg_hr: 56,
      hrv: 55,
      respiratory_rate: 13.9,
      bed_temp: 33.2,
      tnt_count: 8,
      latency: 600,
    }),
  ),
}));

vi.mock("../../api/recovery", () => ({
  fetchRecovery: vi.fn(() =>
    Promise.resolve([
      {
        id: 1,
        date: "2026-05-22",
        source: "whoop",
        recovery_score: 70,
        hrv: 60,
        resting_hr: 55,
        spo2: 96.0,
        strain_score: 10.2,
        skin_temp: 33.0,
        calories: 2300,
      },
    ]),
  ),
}));

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: "imperial" }),
  formatTemperature: (c: number | null | undefined) =>
    c == null ? "—" : `${Math.round(c)}°`,
}));

import { MorningStatusCard } from "./MorningStatusCard";

describe("MorningStatusCard", () => {
  it("navigates to /sleep when the card is clicked", () => {
    navigateMock.mockClear();
    renderWithQuery(<MorningStatusCard />);

    const card = screen.getByRole("button", {
      name: "Open Sleep & Recovery details",
    });
    fireEvent.click(card);

    expect(navigateMock).toHaveBeenCalledWith("/sleep");
  });

  it("navigates to /sleep when Enter is pressed", () => {
    navigateMock.mockClear();
    renderWithQuery(<MorningStatusCard />);

    const card = screen.getByRole("button", {
      name: "Open Sleep & Recovery details",
    });
    fireEvent.keyDown(card, { key: "Enter" });

    expect(navigateMock).toHaveBeenCalledWith("/sleep");
  });
});
