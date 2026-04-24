import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockedNavigate = vi.fn();

vi.mock("react-router-dom", () => ({
  Link: ({ children, to }: { children: ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
  useNavigate: () => mockedNavigate,
}));

vi.mock("../api/strength", () => ({
  createStrengthSession: vi.fn(),
  fetchStrengthExercises: vi.fn(),
  fetchStrengthProgression: vi.fn(),
}));

vi.mock("../api/activities", () => ({
  fetchActivities: vi.fn(),
}));

import StrengthEntry from "./StrengthEntry";
import { fetchActivities } from "../api/activities";
import {
  createStrengthSession,
  fetchStrengthExercises,
  fetchStrengthProgression,
} from "../api/strength";

const mockedCreateStrengthSession = vi.mocked(createStrengthSession);
const mockedFetchStrengthExercises = vi.mocked(fetchStrengthExercises);
const mockedFetchStrengthProgression = vi.mocked(fetchStrengthProgression);
const mockedFetchActivities = vi.mocked(fetchActivities);

const switchToRetro = () =>
  fireEvent.click(screen.getByRole("radio", { name: /retro/i }));

describe("StrengthEntry", () => {
  beforeEach(() => {
    mockedFetchStrengthExercises.mockResolvedValue(["Squat"]);
    mockedFetchStrengthProgression.mockResolvedValue([]);
    mockedFetchActivities.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows a fallback save error when submission fails with a non-Error value", async () => {
    mockedCreateStrengthSession.mockRejectedValue("bad payload");

    render(<StrengthEntry />);
    switchToRetro();

    fireEvent.change(screen.getByLabelText("Exercise name"), {
      target: { value: "Squat" },
    });
    fireEvent.change(screen.getByLabelText("Reps"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save session/i }));

    await waitFor(() => expect(mockedCreateStrengthSession).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Failed to save session")).toBeInTheDocument();
    expect(mockedNavigate).not.toHaveBeenCalled();
  });

  it("in retro mode, generates set numbers from card order and strips performed_at", async () => {
    mockedCreateStrengthSession.mockResolvedValue({ created: 2, session: null });

    render(<StrengthEntry />);
    switchToRetro();

    fireEvent.change(screen.getByLabelText("Exercise name"), {
      target: { value: "Squat" },
    });
    fireEvent.change(screen.getByLabelText("Reps"), {
      target: { value: "5" },
    });
    // Stepper "+" on weight: empty → 2.5.
    fireEvent.click(screen.getByRole("button", { name: /increase weight/i }));
    fireEvent.click(screen.getByRole("button", { name: /\+ add set/i }));

    const repsInputs = screen.getAllByLabelText("Reps");
    expect(repsInputs).toHaveLength(2);
    fireEvent.change(repsInputs[1], { target: { value: "3" } });

    fireEvent.click(screen.getByRole("button", { name: /save session/i }));

    await waitFor(() => expect(mockedCreateStrengthSession).toHaveBeenCalledTimes(1));
    const payload = mockedCreateStrengthSession.mock.calls[0][0];
    expect(payload.sets).toEqual([
      expect.objectContaining({
        exercise_name: "Squat",
        set_number: 1,
        reps: 5,
        weight_kg: 2.5,
        performed_at: null,
      }),
      expect.objectContaining({
        exercise_name: "Squat",
        set_number: 2,
        reps: 3,
        weight_kg: null,
        performed_at: null,
      }),
    ]);
  });

  it("in live mode, 'Log' stamps performed_at, auto-appends a set, and saves only logged sets", async () => {
    mockedCreateStrengthSession.mockResolvedValue({ created: 1, session: null });

    render(<StrengthEntry />);
    // Live is default.
    fireEvent.change(screen.getByLabelText("Exercise name"), {
      target: { value: "Squat" },
    });
    fireEvent.change(screen.getByLabelText("Reps"), { target: { value: "5" } });

    // Before logging, save is disabled.
    expect(screen.getByRole("button", { name: /save session/i })).toBeDisabled();

    // Log the first set → stamps performed_at and auto-appends an empty row.
    fireEvent.click(screen.getByRole("button", { name: /^log$/i }));

    // The logged timestamp is shown; a fresh unlogged row's Log button
    // remains, but the second unlogged row should not be included in save.
    expect(screen.getAllByLabelText("Reps")).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: /save session/i }));
    await waitFor(() => expect(mockedCreateStrengthSession).toHaveBeenCalledTimes(1));

    const payload = mockedCreateStrengthSession.mock.calls[0][0];
    expect(payload.sets).toHaveLength(1);
    expect(payload.sets[0]).toEqual(
      expect.objectContaining({
        exercise_name: "Squat",
        set_number: 1,
        reps: 5,
        performed_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/),
      })
    );
  });
});
