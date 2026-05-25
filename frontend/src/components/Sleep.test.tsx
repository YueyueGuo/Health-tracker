// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  createTestQueryClient,
  renderWithQuery,
} from "../test/renderWithQuery";
import type { SleepSession } from "../api/sleep";
import type { RecoveryRecord } from "../api/recovery";

const whoopRow: SleepSession = {
  id: 1,
  source: "whoop",
  external_id: "w",
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

const eightRow: SleepSession = {
  id: 2,
  source: "eight_sleep",
  external_id: "e",
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

const recoveryRow: RecoveryRecord = {
  id: 5,
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

vi.mock("../hooks/useUnits", () => ({
  useUnits: () => ({ units: "imperial" }),
  formatTemperature: (c: number | null | undefined) =>
    c == null ? "—" : `${Math.round(c)}°`,
}));

vi.mock("../api/sleep", () => ({
  fetchSleepSessions: vi.fn(() => Promise.resolve([whoopRow, eightRow])),
  fetchLatestSleep: vi.fn((opts?: { source?: string }) =>
    Promise.resolve(opts?.source === "whoop" ? whoopRow : eightRow),
  ),
}));

vi.mock("../api/recovery", () => ({
  fetchRecovery: vi.fn(() => Promise.resolve([recoveryRow])),
}));

import Sleep from "./Sleep";
import { fetchLatestSleep, fetchSleepSessions } from "../api/sleep";
import { fetchRecovery } from "../api/recovery";

describe("Sleep page", () => {
  beforeEach(() => {
    vi.mocked(fetchLatestSleep).mockReset();
    vi.mocked(fetchSleepSessions).mockReset();
    vi.mocked(fetchRecovery).mockReset();

    // Default mocks — match the legacy fixtures so existing tests keep their
    // shape. Individual tests can override with `mockImplementation` /
    // `mockResolvedValue` to exercise date-specific responses.
    vi.mocked(fetchSleepSessions).mockResolvedValue([whoopRow, eightRow]);
    vi.mocked(fetchLatestSleep).mockImplementation((opts) =>
      Promise.resolve(opts?.source === "whoop" ? whoopRow : eightRow),
    );
    vi.mocked(fetchRecovery).mockResolvedValue([recoveryRow]);
  });

  it("renders the detail card inside an AppShell-style container", async () => {
    const { container } = renderWithQuery(
      <MemoryRouter initialEntries={["/sleep"]}>
        <Sleep />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", { name: "Sleep & Recovery" }),
    ).toBeInTheDocument();

    // No legacy sidebar shell should be on the page.
    expect(container.querySelector(".app-layout")).toBeNull();
    expect(container.querySelector(".sidebar")).toBeNull();
  });

  it("passes the ?date= query param as onOrBefore for both sources", async () => {
    renderWithQuery(
      <MemoryRouter initialEntries={["/sleep?date=2025-05-10"]}>
        <Sleep />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", { name: "Sleep & Recovery" }),
    ).toBeInTheDocument();

    expect(fetchLatestSleep).toHaveBeenCalledWith(
      expect.objectContaining({ source: "whoop", onOrBefore: "2025-05-10" }),
    );
    expect(fetchLatestSleep).toHaveBeenCalledWith(
      expect.objectContaining({
        source: "eight_sleep",
        onOrBefore: "2025-05-10",
      }),
    );
  });

  it("omits onOrBefore when no ?date= param is present (dashboard entry point)", async () => {
    renderWithQuery(
      <MemoryRouter initialEntries={["/sleep"]}>
        <Sleep />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", { name: "Sleep & Recovery" }),
    ).toBeInTheDocument();

    expect(fetchLatestSleep).toHaveBeenCalledWith(
      expect.objectContaining({ source: "whoop", onOrBefore: undefined }),
    );
    expect(fetchLatestSleep).toHaveBeenCalledWith(
      expect.objectContaining({
        source: "eight_sleep",
        onOrBefore: undefined,
      }),
    );
  });

  it("includes the date in the cache key so navigating to a new night refetches", async () => {
    const first = renderWithQuery(
      <MemoryRouter initialEntries={["/sleep?date=2025-05-10"]}>
        <Sleep />
      </MemoryRouter>,
    );
    expect(
      await screen.findByRole("heading", { name: "Sleep & Recovery" }),
    ).toBeInTheDocument();
    first.unmount();

    const second = renderWithQuery(
      <MemoryRouter initialEntries={["/sleep?date=2025-05-09"]}>
        <Sleep />
      </MemoryRouter>,
    );
    expect(
      await screen.findByRole("heading", { name: "Sleep & Recovery" }),
    ).toBeInTheDocument();
    second.unmount();

    const onOrBeforeArgs = vi
      .mocked(fetchLatestSleep)
      .mock.calls.map(([opts]) => opts?.onOrBefore);
    expect(onOrBeforeArgs).toContain("2025-05-10");
    expect(onOrBeforeArgs).toContain("2025-05-09");
  });
});
