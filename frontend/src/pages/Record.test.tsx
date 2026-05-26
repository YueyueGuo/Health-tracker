// @vitest-environment jsdom
import { act, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithQuery } from "../test/renderWithQuery";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

const createStrengthSession = vi.fn().mockResolvedValue({
  created: 1,
  session: null,
});
vi.mock("../api/strength", () => ({
  createStrengthSession: (...args: unknown[]) =>
    (createStrengthSession as unknown as (...a: unknown[]) => Promise<unknown>)(
      ...args
    ),
  fetchStrengthExercises: () => Promise.resolve(["Squat", "Deadlift"]),
  fetchStrengthProgression: () => Promise.resolve([]),
}));

import Record from "./Record";

function renderWithRouter() {
  return renderWithQuery(
    <MemoryRouter initialEntries={["/record"]}>
      <Routes>
        <Route path="/record" element={<Record />} />
      </Routes>
    </MemoryRouter>
  );
}

describe("Record page", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    createStrengthSession.mockClear();
    window.localStorage.clear();
  });

  it("renders the timer header and one empty exercise card", () => {
    renderWithRouter();
    expect(screen.getByRole("heading", { name: "Strength" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Exercise Name")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeInTheDocument();
  });

  it("logs a set, saves, and navigates to /history", async () => {
    renderWithRouter();
    fireEvent.change(screen.getByPlaceholderText("Exercise Name"), {
      target: { value: "Bench Press" },
    });
    const repsInputs = screen.getAllByLabelText(/Set 1 reps/i);
    fireEvent.change(repsInputs[0], { target: { value: "5" } });
    const weightInputs = screen.getAllByLabelText(/Set 1 weight/i);
    fireEvent.change(weightInputs[0], { target: { value: "60" } });

    fireEvent.click(screen.getByRole("button", { name: "Log set 1" }));

    // After logging, Finish is enabled.
    const finishBtn = await screen.findByRole("button", { name: "Finish" });
    expect(finishBtn).not.toBeDisabled();

    fireEvent.click(finishBtn);

    await waitFor(() => expect(createStrengthSession).toHaveBeenCalledTimes(1));
    const payload = createStrengthSession.mock.calls[0][0] as {
      date: string;
      activity_id: number | null;
      sets: Array<Record<string, unknown>>;
    };
    expect(payload.activity_id).toBeNull();
    expect(payload.sets).toHaveLength(1);
    expect(payload.sets[0]).toMatchObject({
      exercise_name: "Bench Press",
      reps: 5,
      weight_kg: 60,
      set_number: 1,
    });
    expect(payload.sets[0].performed_at).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/
    );

    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith("/history")
    );
    expect(
      window.localStorage.getItem("health-tracker:record-draft:v2")
    ).toBeNull();
  });

  it("blocks Finish when no sets are logged", () => {
    renderWithRouter();
    expect(screen.getByRole("button", { name: "Finish" })).toBeDisabled();
  });

  it("restores an in-progress draft after leaving and returning", async () => {
    const { unmount } = renderWithRouter();
    fireEvent.change(screen.getByPlaceholderText("Exercise Name"), {
      target: { value: "Bench Press" },
    });
    fireEvent.change(screen.getAllByLabelText(/Set 1 reps/i)[0], {
      target: { value: "5" },
    });
    fireEvent.change(screen.getAllByLabelText(/Set 1 weight/i)[0], {
      target: { value: "60" },
    });

    await waitFor(() =>
      expect(
        window.localStorage.getItem("health-tracker:record-draft:v2")
      ).toContain("Bench Press")
    );

    unmount();
    renderWithRouter();

    expect(screen.getByDisplayValue("Bench Press")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/Set 1 reps/i)[0]).toHaveValue(5);
    expect(screen.getAllByLabelText(/Set 1 weight/i)[0]).toHaveValue(60);
  });

  it("blocks logging a set with malformed numeric values", () => {
    renderWithRouter();
    fireEvent.change(screen.getByPlaceholderText("Exercise Name"), {
      target: { value: "Bench Press" },
    });
    fireEvent.change(screen.getAllByLabelText(/Set 1 reps/i)[0], {
      target: { value: "5.5" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Log set 1" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "whole-number reps"
    );
    expect(screen.getByRole("button", { name: "Finish" })).toBeDisabled();
  });

  it("emits matching superset_group_id for consecutive linked exercises", async () => {
    renderWithRouter();

    // Exercise 1: name + one set.
    const nameInputs = () => screen.getAllByPlaceholderText("Exercise Name");
    fireEvent.change(nameInputs()[0], { target: { value: "Pull Up" } });
    fireEvent.change(screen.getAllByLabelText(/Set 1 reps/i)[0], {
      target: { value: "8" },
    });
    fireEvent.change(screen.getAllByLabelText(/Set 1 weight/i)[0], {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Log set 1" }));

    // Add exercise 2 first (the link button only appears once a next
    // exercise exists, since `showLinkButton` checks position in the list).
    fireEvent.click(screen.getByRole("button", { name: /add exercise/i }));

    // Now link exercise 1 → exercise 2.
    fireEvent.click(
      screen.getByRole("button", { name: /create superset/i }),
    );

    // Exercise 2: name + one set.
    fireEvent.change(nameInputs()[1], { target: { value: "Dip" } });
    const allRepsInputs = screen.getAllByLabelText(/Set 1 reps/i);
    fireEvent.change(allRepsInputs[allRepsInputs.length - 1], {
      target: { value: "10" },
    });
    const allWeightInputs = screen.getAllByLabelText(/Set 1 weight/i);
    fireEvent.change(allWeightInputs[allWeightInputs.length - 1], {
      target: { value: "0" },
    });
    // Each ExerciseCard has its own "Log set 1" button; the second card's
    // button is the most recently rendered one.
    const logButtons = screen.getAllByRole("button", { name: /log set 1/i });
    fireEvent.click(logButtons[logButtons.length - 1]);

    const finishBtn = await screen.findByRole("button", { name: "Finish" });
    expect(finishBtn).not.toBeDisabled();
    fireEvent.click(finishBtn);

    await waitFor(() => expect(createStrengthSession).toHaveBeenCalledTimes(1));
    const payload = createStrengthSession.mock.calls[0][0] as {
      sets: Array<{
        exercise_name: string;
        superset_group_id: number | null;
        order_index: number;
      }>;
      started_at: string | null;
      ended_at: string | null;
    };
    const byName = new Map(payload.sets.map((s) => [s.exercise_name, s]));
    expect(byName.get("Pull Up")?.superset_group_id).not.toBeNull();
    expect(byName.get("Pull Up")?.superset_group_id).toBe(
      byName.get("Dip")?.superset_group_id,
    );
    expect(byName.get("Pull Up")?.order_index).toBe(0);
    expect(byName.get("Dip")?.order_index).toBe(1);
    // Naive-local ISO (no tz suffix), stamped at finish.
    expect(payload.ended_at).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/,
    );
  });
});

// --- Timer regression suite (wall-clock fidelity across backgrounding) ---

const DRAFT_KEY_V2 = "health-tracker:record-draft:v2";

function getTimerText(): string {
  // The header renders the MM:SS string in a `tabular-nums` span next to a
  // Clock icon. Match the format directly to avoid coupling to markup.
  const els = screen
    .getAllByText(/^\d{2}:\d{2}$/)
    .filter((el) => el.tagName.toLowerCase() === "span");
  if (els.length === 0) throw new Error("timer display not found");
  return els[0].textContent ?? "";
}

describe("Record timer wall-clock fidelity", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    createStrengthSession.mockClear();
    window.localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-26T10:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("timer reflects wall-clock time after a backgrounded interval", () => {
    renderWithRouter();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    // Simulate the tab being backgrounded for 60s: jump system time forward
    // without letting the queued setInterval fire.
    act(() => {
      vi.setSystemTime(Date.now() + 60_000);
    });
    // Fire the next 1Hz tick so React re-renders with the new `now`.
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    // 60s skipped + 1s tick advance => 01:00 or 01:01 depending on rounding.
    expect(getTimerText()).toMatch(/^01:0[01]$/);
  });

  it("mount restoration from persisted startedAtMs shows correct elapsed", () => {
    const now = Date.now();
    window.localStorage.setItem(
      DRAFT_KEY_V2,
      JSON.stringify({
        version: 2,
        date: "2026-05-26",
        exercises: [
          {
            key: 1,
            name: "",
            notes: "",
            showNotes: false,
            linkedToNext: false,
            sets: [
              { key: 2, weight: "", reps: "", rpe: "", performed_at: null },
              { key: 3, weight: "", reps: "", rpe: "", performed_at: null },
              { key: 4, weight: "", reps: "", rpe: "", performed_at: null },
            ],
          },
        ],
        isRunning: true,
        startedAtMs: now - 120_000,
        accumulatedSecs: 0,
      }),
    );

    renderWithRouter();

    expect(getTimerText()).toBe("02:00");
  });

  it("visibilitychange to visible immediately resyncs elapsed", () => {
    renderWithRouter();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    // Background: bump wall-clock 30s without firing the interval.
    act(() => {
      vi.setSystemTime(Date.now() + 30_000);
    });
    // Tab becomes visible — fire the listener directly without advancing
    // timers, so we prove the recompute didn't rely on the next tick.
    act(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => "visible",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(getTimerText()).toBe("00:30");
  });

  it("pause then resume accumulates wall-clock time across pause", () => {
    renderWithRouter();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    // Run honestly for 30s: 30 ticks fire while system time advances.
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(getTimerText()).toBe("00:30");

    // Pause and let 5 minutes of wall-clock pass with no ticks needed.
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    act(() => {
      vi.setSystemTime(Date.now() + 5 * 60_000);
    });
    // Still paused: timer should not have advanced beyond the committed 30s.
    expect(getTimerText()).toBe("00:30");

    // Resume and let 10s pass honestly.
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(getTimerText()).toBe("00:40");
  });
});
