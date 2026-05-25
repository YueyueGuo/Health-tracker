// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import type { SleepSession } from "../../api/sleep";
import type { RecoveryRecord } from "../../api/recovery";

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: "imperial" }),
  formatTemperature: (c: number | null | undefined) =>
    c == null ? "—" : `${Math.round(c)}°`,
}));

const { mockNavigate } = vi.hoisted(() => ({ mockNavigate: vi.fn() }));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

import { SleepRecoveryDetailsCard } from "./SleepRecoveryDetailsCard";

const whoopSleep: SleepSession = {
  id: 101,
  source: "whoop",
  external_id: "w-1",
  date: "2026-05-22",
  bed_time: "2026-05-21T23:00:00",
  wake_time: "2026-05-22T06:30:00",
  total_duration: 450,
  deep_sleep: 90,
  rem_sleep: 100,
  light_sleep: 240,
  awake_time: 20,
  sleep_score: 88,
  sleep_fitness_score: null,
  avg_hr: 54,
  hrv: 62,
  respiratory_rate: 14.2,
  bed_temp: null,
  tnt_count: null,
  latency: 540,
  sleep_efficiency: 92.5,
  sleep_consistency: 81,
  sleep_debt_min: 30,
};

const eightSleep: SleepSession = {
  id: 202,
  source: "eight_sleep",
  external_id: "e-1",
  date: "2026-05-22",
  bed_time: "2026-05-21T23:05:00",
  wake_time: "2026-05-22T06:25:00",
  total_duration: 440,
  deep_sleep: 80,
  rem_sleep: 95,
  light_sleep: 250,
  awake_time: 15,
  sleep_score: 84,
  sleep_fitness_score: null,
  avg_hr: 56,
  hrv: 55,
  respiratory_rate: 13.9,
  bed_temp: 33.2,
  tnt_count: 8,
  latency: 600,
  wake_count: 3,
  waso_duration: 12,
};

const recovery: RecoveryRecord = {
  id: 9,
  date: "2026-05-22",
  source: "whoop",
  recovery_score: 75,
  hrv: 62,
  resting_hr: 54,
  spo2: 96.5,
  strain_score: 12.4,
  skin_temp: 33.5,
  calories: 2400,
};

describe("SleepRecoveryDetailsCard", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it("renders both source labels and the score circles", () => {
    render(
      <MemoryRouter>
        <SleepRecoveryDetailsCard
          whoopSleep={whoopSleep}
          eightSleep={eightSleep}
          recovery={recovery}
        />
      </MemoryRouter>,
    );

    // Source labels appear in multiple places (badges + table headers).
    expect(screen.getAllByText("WHOOP").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Eight Sleep").length).toBeGreaterThanOrEqual(1);

    // Score circles: recovery score (75%) and Eight sleep score (84) both render.
    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(screen.getByText("84")).toBeInTheDocument();

    // Header
    expect(
      screen.getByRole("heading", { name: "Sleep & Recovery" }),
    ).toBeInTheDocument();
  });

  it("renders even when recovery is missing", () => {
    render(
      <MemoryRouter>
        <SleepRecoveryDetailsCard
          whoopSleep={whoopSleep}
          eightSleep={eightSleep}
          recovery={null}
        />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { name: "Sleep & Recovery" }),
    ).toBeInTheDocument();
    // Recovery circle falls back to em-dash placeholder.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });

  it("back button falls back to dashboard when entered via deep link", () => {
    // Single MemoryRouter entry — react-router classifies the initial
    // navigation as "POP", mimicking a fresh-tab deep link to /sleep.
    render(
      <MemoryRouter initialEntries={["/sleep"]}>
        <SleepRecoveryDetailsCard
          whoopSleep={whoopSleep}
          eightSleep={eightSleep}
          recovery={recovery}
        />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Go back" }));

    expect(mockNavigate).toHaveBeenCalledWith("/", { replace: true });
    expect(mockNavigate).not.toHaveBeenCalledWith(-1);
  });

  it("back button calls navigate(-1) when entered from within the app", () => {
    // Drive a real in-app PUSH (Link click) so useNavigationType reports
    // "PUSH" when the detail card mounts. A static initialIndex doesn't
    // work — MemoryRouter classifies its initial render as "POP".
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<Link to="/sleep">Open sleep</Link>} />
          <Route
            path="/sleep"
            element={
              <SleepRecoveryDetailsCard
                whoopSleep={whoopSleep}
                eightSleep={eightSleep}
                recovery={recovery}
              />
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("link", { name: "Open sleep" }));
    fireEvent.click(screen.getByRole("button", { name: "Go back" }));

    expect(mockNavigate).toHaveBeenCalledWith(-1);
    expect(mockNavigate).not.toHaveBeenCalledWith("/", { replace: true });
  });
});
