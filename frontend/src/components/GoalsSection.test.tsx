import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GoalsSection from "./GoalsSection";

vi.mock("../api/goals", () => ({
  createGoal: vi.fn(),
  deleteGoal: vi.fn(),
  listGoals: vi.fn(),
  patchGoal: vi.fn(),
  setPrimaryGoal: vi.fn(),
}));

import {
  createGoal,
  deleteGoal,
  listGoals,
  patchGoal,
  setPrimaryGoal,
} from "../api/goals";

const mockedCreateGoal = vi.mocked(createGoal);
const mockedDeleteGoal = vi.mocked(deleteGoal);
const mockedListGoals = vi.mocked(listGoals);
const mockedPatchGoal = vi.mocked(patchGoal);
const mockedSetPrimaryGoal = vi.mocked(setPrimaryGoal);

const goals = [
  {
    id: 1,
    race_type: "Half Marathon",
    description: "Fall goal race",
    target_date: "2026-09-20",
    is_primary: true,
    status: "active" as const,
  },
  {
    id: 2,
    race_type: "10k",
    description: null,
    target_date: "2026-06-15",
    is_primary: false,
    status: "active" as const,
  },
];

describe("GoalsSection", () => {
  beforeEach(() => {
    mockedListGoals.mockResolvedValue(goals);
    vi.stubGlobal("confirm", vi.fn(() => true));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("creates a new goal", async () => {
    mockedCreateGoal.mockResolvedValue({
      id: 3,
      race_type: "Marathon",
      description: "Goal race",
      target_date: "2026-10-10",
      is_primary: true,
      status: "active",
    });

    const { container } = render(<GoalsSection />);

    await screen.findByText("Goals");
    fireEvent.click(screen.getByRole("button", { name: "New goal" }));
    fireEvent.change(
      screen.getByPlaceholderText("Race type (e.g. Marathon, Half-Ironman, 10k)"),
      { target: { value: "Marathon" } }
    );
    const dateInput = container.querySelector('input[type="date"]');
    expect(dateInput).not.toBeNull();
    fireEvent.change(dateInput!, {
      target: { value: "2026-10-10" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("Notes (optional): course, goal time, priority …"),
      { target: { value: "Goal race" } }
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockedCreateGoal).toHaveBeenCalledWith({
        race_type: "Marathon",
        target_date: "2026-10-10",
        description: "Goal race",
        is_primary: true,
      })
    );
  });

  it("makes a secondary goal primary and changes status", async () => {
    mockedSetPrimaryGoal.mockResolvedValue(goals[1]);
    mockedPatchGoal.mockResolvedValue({ ...goals[1], status: "completed" });

    render(<GoalsSection />);

    await screen.findByText("10k");
    fireEvent.click(screen.getByRole("button", { name: "Make primary" }));
    await waitFor(() => expect(mockedSetPrimaryGoal).toHaveBeenCalledWith(2));

    fireEvent.change(screen.getAllByDisplayValue("active")[1], {
      target: { value: "completed" },
    });
    await waitFor(() =>
      expect(mockedPatchGoal).toHaveBeenCalledWith(2, { status: "completed" })
    );
  });

  it("deletes a goal after confirmation", async () => {
    mockedDeleteGoal.mockResolvedValue(undefined);

    render(<GoalsSection />);

    await screen.findByText("10k");
    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);

    await waitFor(() => expect(mockedDeleteGoal).toHaveBeenCalled());
  });
});
