// @vitest-environment jsdom
import { fireEvent, render, screen, within } from "@testing-library/react";
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

  describe("Sleep Stages bar header strip", () => {
    const baseWhoop: SleepSession = {
      ...whoopSleep,
      bed_time: "2026-05-24T23:14:00",
      wake_time: "2026-05-25T06:42:00",
      total_duration: 408,
    };
    const baseEight: SleepSession = {
      ...eightSleep,
      bed_time: "2026-05-24T23:20:00",
      wake_time: "2026-05-25T06:38:00",
      total_duration: 398,
    };

    it("renders total duration + bed→wake time for both sources when present", () => {
      render(
        <MemoryRouter>
          <SleepRecoveryDetailsCard
            whoopSleep={baseWhoop}
            eightSleep={baseEight}
            recovery={recovery}
          />
        </MemoryRouter>,
      );

      const whoopSummary = screen.getByTestId("whoop-bar-summary");
      expect(whoopSummary.textContent).toContain("6h 48m");
      expect(whoopSummary.textContent).toContain("11:14 PM");
      expect(whoopSummary.textContent).toContain("6:42 AM");

      const eightSummary = screen.getByTestId("eight-bar-summary");
      expect(eightSummary.textContent).toContain("6h 38m");
      expect(eightSummary.textContent).toContain("11:20 PM");
      expect(eightSummary.textContent).toContain("6:38 AM");
    });

    it("shows total duration without bed/wake when bed_time is null", () => {
      const whoopWithoutBed: SleepSession = {
        ...baseWhoop,
        bed_time: null,
      };
      render(
        <MemoryRouter>
          <SleepRecoveryDetailsCard
            whoopSleep={whoopWithoutBed}
            eightSleep={null}
            recovery={null}
          />
        </MemoryRouter>,
      );

      const whoopSummary = screen.getByTestId("whoop-bar-summary");
      expect(whoopSummary.textContent).toContain("6h 48m");
      expect(whoopSummary.textContent).not.toContain("PM");
      expect(whoopSummary.textContent).not.toContain("AM");
    });

    it("shows bed/wake without total duration when total_duration is null", () => {
      const whoopWithoutTotal: SleepSession = {
        ...baseWhoop,
        total_duration: null,
      };
      render(
        <MemoryRouter>
          <SleepRecoveryDetailsCard
            whoopSleep={whoopWithoutTotal}
            eightSleep={null}
            recovery={null}
          />
        </MemoryRouter>,
      );

      const whoopSummary = screen.getByTestId("whoop-bar-summary");
      expect(whoopSummary.textContent).toContain("11:14 PM");
      expect(whoopSummary.textContent).toContain("6:42 AM");
      expect(whoopSummary.textContent).not.toContain("6h");
    });

    it("omits the right-side strip entirely when total_duration AND bed/wake are all null", () => {
      const whoopBare: SleepSession = {
        ...baseWhoop,
        bed_time: null,
        wake_time: null,
        total_duration: null,
      };
      render(
        <MemoryRouter>
          <SleepRecoveryDetailsCard
            whoopSleep={whoopBare}
            eightSleep={null}
            recovery={null}
          />
        </MemoryRouter>,
      );

      expect(screen.queryByTestId("whoop-bar-summary")).toBeNull();
      // No broken middot or dashed-connector artifacts.
      expect(screen.queryByText(/^·$/)).toBeNull();
      expect(screen.queryByText(/—:—/)).toBeNull();
    });

    it("uses 12-hour formatting (AM / PM) in the bar header", () => {
      render(
        <MemoryRouter>
          <SleepRecoveryDetailsCard
            whoopSleep={baseWhoop}
            eightSleep={null}
            recovery={null}
          />
        </MemoryRouter>,
      );

      const whoopSummary = screen.getByTestId("whoop-bar-summary");
      // 11:14 PM → bed; 6:42 AM → wake.
      expect(whoopSummary.textContent).toMatch(/PM/);
      expect(whoopSummary.textContent).toMatch(/AM/);
    });
  });

  describe("Sleep Stages bar segment labels", () => {
    it("renders in-segment percentage label for wide segments (>= 8%)", () => {
      // Light ~50% of total → clearly above the 8% threshold.
      const wideStages: SleepSession = {
        ...whoopSleep,
        deep_sleep: 30,
        rem_sleep: 30,
        light_sleep: 100,
        awake_time: 40,
      };
      render(
        <MemoryRouter>
          <SleepRecoveryDetailsCard
            whoopSleep={wideStages}
            eightSleep={null}
            recovery={null}
          />
        </MemoryRouter>,
      );

      // Light = 100/200 = 50%. The visible span should render.
      expect(screen.getByText("50%")).toBeInTheDocument();
    });

    it("suppresses the visible label for narrow segments but keeps the title attribute", () => {
      // Awake ~2% of total. Below threshold of 8 → no visible label, but
      // the segment div still carries `title="Awake 2%"`.
      const narrowAwake: SleepSession = {
        ...whoopSleep,
        deep_sleep: 100,
        rem_sleep: 100,
        light_sleep: 296,
        awake_time: 8, // 8 / 504 ≈ 1.6% → rounds to 2%
      };
      render(
        <MemoryRouter>
          <SleepRecoveryDetailsCard
            whoopSleep={narrowAwake}
            eightSleep={null}
            recovery={null}
          />
        </MemoryRouter>,
      );

      // No visible "2%" text node (would-be span is suppressed).
      expect(screen.queryByText("2%")).toBeNull();
      // But the segment element still exposes the value via title/aria-label.
      const segment = screen.getByLabelText(/^Awake \d+%$/);
      expect(segment.getAttribute("title")).toMatch(/^Awake \d+%$/);
    });
  });

  describe("Sleep Stages comparison table", () => {
    it("renders bare durations without parenthetical percentages", () => {
      render(
        <MemoryRouter>
          <SleepRecoveryDetailsCard
            whoopSleep={whoopSleep}
            eightSleep={eightSleep}
            recovery={recovery}
          />
        </MemoryRouter>,
      );

      // No `(NN%)` parenthetical anywhere in the rendered card.
      expect(screen.queryByText(/\(\d+%\)/)).toBeNull();
      // Sanity: stage rows still show duration values like "1h 30m" / "20m".
      // WHOOP deep = 90 → "1h 30m"; awake = 20 → "20m".
      expect(screen.getByText("1h 30m")).toBeInTheDocument();
      expect(screen.getByText("20m")).toBeInTheDocument();
    });
  });
});
