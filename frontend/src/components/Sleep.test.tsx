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
    // Share a single QueryClient between the two renders so the second render
    // can read what the first cached. `renderWithQuery` otherwise creates a
    // fresh client per call, which would make this test pass even if
    // `dateParam` were silently dropped from the useApi key (the fetcher would
    // still be invoked again on the second render because the cache is empty).
    const queryClient = createTestQueryClient();
    const first = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/sleep?date=2025-05-10"]}>
          <Sleep />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(
      await screen.findByRole("heading", { name: "Sleep & Recovery" }),
    ).toBeInTheDocument();
    first.unmount();

    const second = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/sleep?date=2025-05-09"]}>
          <Sleep />
        </MemoryRouter>
      </QueryClientProvider>,
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

  it("renders the date-scoped Eight Sleep score, not the newest from the pool", async () => {
    // Pool has rows for May 8, 10 and 12; the deep-link asks for May 10.
    // Before the rendering fix, `resolveSleepPairForCard` walked the pool
    // newest-first and bound the card to the May 12 (score 91) row even
    // though /sleep/latest?on_or_before=2025-05-10 correctly returned May 10
    // (score 73). The card must now follow the date-scoped fetch.
    const poolMay08Whoop: SleepSession = {
      ...whoopRow,
      id: 100,
      date: "2025-05-08",
      sleep_score: 65,
    };
    const poolMay08Eight: SleepSession = {
      ...eightRow,
      id: 101,
      date: "2025-05-08",
      sleep_score: 62,
    };
    const poolMay10Whoop: SleepSession = {
      ...whoopRow,
      id: 102,
      date: "2025-05-10",
      sleep_score: 70,
    };
    const poolMay10Eight: SleepSession = {
      ...eightRow,
      id: 103,
      date: "2025-05-10",
      sleep_score: 73,
    };
    const poolMay12Whoop: SleepSession = {
      ...whoopRow,
      id: 104,
      date: "2025-05-12",
      sleep_score: 88,
    };
    const poolMay12Eight: SleepSession = {
      ...eightRow,
      id: 105,
      date: "2025-05-12",
      sleep_score: 91,
    };

    vi.mocked(fetchSleepSessions).mockResolvedValue([
      poolMay12Whoop,
      poolMay12Eight,
      poolMay10Whoop,
      poolMay10Eight,
      poolMay08Whoop,
      poolMay08Eight,
    ]);
    vi.mocked(fetchLatestSleep).mockImplementation((opts) => {
      // The deep-linked request scopes both providers to May 10.
      if (opts?.onOrBefore === "2025-05-10") {
        return Promise.resolve(
          opts.source === "whoop" ? poolMay10Whoop : poolMay10Eight,
        );
      }
      // Anything else (the dashboard "latest" entry point) yields May 12.
      return Promise.resolve(
        opts?.source === "whoop" ? poolMay12Whoop : poolMay12Eight,
      );
    });
    vi.mocked(fetchRecovery).mockResolvedValue([
      { ...recoveryRow, id: 200, date: "2025-05-10", recovery_score: 55 },
    ]);

    renderWithQuery(
      <MemoryRouter initialEntries={["/sleep?date=2025-05-10"]}>
        <Sleep />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", { name: "Sleep & Recovery" }),
    ).toBeInTheDocument();

    // Eight Sleep score circle should read 73 (May 10), not 91 (May 12 pool
    // newest). The recovery circle should also be the May 10 row at 55%.
    expect(await screen.findByText("73")).toBeInTheDocument();
    expect(screen.queryByText("91")).not.toBeInTheDocument();
    expect(screen.getByText("55%")).toBeInTheDocument();
  });
});
