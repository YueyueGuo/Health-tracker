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

  it("generates set numbers from card order and stepper increments the weight", async () => {
    mockedCreateStrengthSession.mockResolvedValue({ created: 2, session: null });

    render(<StrengthEntry />);

    fireEvent.change(screen.getByLabelText("Exercise name"), {
      target: { value: "Squat" },
    });
    fireEvent.change(screen.getByLabelText("Reps"), {
      target: { value: "5" },
    });
    // Stepper "+" on weight should bump 0 → 2.5.
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
      }),
      expect.objectContaining({
        exercise_name: "Squat",
        set_number: 2,
        reps: 3,
        weight_kg: null,
      }),
    ]);
  });
});
