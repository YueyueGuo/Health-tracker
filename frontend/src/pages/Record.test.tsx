import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
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
  return render(
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
  });

  it("blocks Finish when no sets are logged", () => {
    renderWithRouter();
    expect(screen.getByRole("button", { name: "Finish" })).toBeDisabled();
  });
});
