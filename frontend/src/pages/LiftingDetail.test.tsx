// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { renderWithQuery } from "../test/renderWithQuery";
import type {
  ExerciseBreakdown,
  StrengthSessionDetail,
} from "../api/strength";

// `StrengthSet` is not exported from the strength api module, so reconstruct
// the minimum shape the page consumes (matches the interface in
// `api/strength.ts`).
type StrengthSet = StrengthSessionDetail["sets"][number];

const fetchStrengthSessionOptional = vi.fn();
vi.mock("../api/strength", () => ({
  fetchStrengthSessionOptional: (...args: unknown[]) =>
    (fetchStrengthSessionOptional as unknown as (
      ...a: unknown[]
    ) => Promise<unknown>)(...args),
}));

vi.mock("../hooks/useUnits", () => ({
  useUnits: () => ({ units: "imperial", setUnits: () => {}, toggle: () => {} }),
}));

import LiftingDetail from "./LiftingDetail";

function makeSet(over: Partial<StrengthSet> = {}): StrengthSet {
  return {
    id: 1,
    activity_id: null,
    date: "2026-05-24",
    exercise_name: "Bench Press",
    set_number: 1,
    reps: 5,
    weight_kg: 80,
    rpe: 8,
    notes: null,
    performed_at: "2026-05-24T17:35:00",
    superset_group_id: null,
    order_index: 0,
    ...over,
  };
}

function makeExercise(over: Partial<ExerciseBreakdown> = {}): ExerciseBreakdown {
  return {
    name: "Bench Press",
    sets: [makeSet()],
    max_weight: 80,
    total_volume: 400,
    est_1rm: 92,
    superset_group_id: null,
    order_index: 0,
    ...over,
  };
}

function renderRoute(date = "2026-05-24") {
  return renderWithQuery(
    <MemoryRouter initialEntries={[`/workouts/lifting/${date}`]}>
      <Routes>
        <Route path="/workouts/lifting/:date" element={<LiftingDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LiftingDetail page", () => {
  beforeEach(() => {
    fetchStrengthSessionOptional.mockReset();
  });

  it("renders summary card + standalone exercises when no supersets", async () => {
    const session: StrengthSessionDetail = {
      date: "2026-05-24",
      activity_id: null,
      link: null,
      segmentation: null,
      hr_curve: null,
      segment_markers: null,
      activity_start_iso: null,
      duration_sec: 3300,
      total_sets: 2,
      total_reps: 10,
      total_volume_kg: 800,
      exercise_count: 2,
      started_at: "2026-05-24T17:30:00",
      ended_at: "2026-05-24T18:25:00",
      sets: [
        makeSet({ id: 1, exercise_name: "Bench Press" }),
        makeSet({
          id: 2,
          exercise_name: "Squat",
          weight_kg: 100,
          reps: 5,
        }),
      ],
      exercises: [
        makeExercise({
          name: "Bench Press",
          order_index: 0,
          superset_group_id: null,
        }),
        makeExercise({
          name: "Squat",
          order_index: 1,
          superset_group_id: null,
          sets: [
            makeSet({
              id: 2,
              exercise_name: "Squat",
              weight_kg: 100,
              reps: 5,
            }),
          ],
          total_volume: 500,
          est_1rm: 117,
          max_weight: 100,
        }),
      ],
    };
    fetchStrengthSessionOptional.mockResolvedValue(session);

    renderRoute("2026-05-24");

    await waitFor(() =>
      expect(screen.getByText("Bench Press")).toBeInTheDocument(),
    );
    expect(screen.getByText("Strength Session")).toBeInTheDocument();
    expect(screen.getByText("Squat")).toBeInTheDocument();
    // No superset bracket should be rendered when all exercises are
    // standalone.
    expect(screen.queryByTestId("superset-bracket")).not.toBeInTheDocument();
  });

  it("groups adjacent exercises sharing a non-null superset_group_id", async () => {
    const session: StrengthSessionDetail = {
      date: "2026-05-24",
      activity_id: null,
      link: null,
      segmentation: null,
      hr_curve: null,
      segment_markers: null,
      activity_start_iso: null,
      duration_sec: 1800,
      total_sets: 4,
      total_reps: 20,
      total_volume_kg: 1200,
      exercise_count: 3,
      started_at: null,
      ended_at: null,
      sets: [],
      exercises: [
        // Two exercises in a superset followed by a standalone.
        makeExercise({
          name: "Pull Up",
          order_index: 0,
          superset_group_id: 1,
          sets: [
            makeSet({ id: 1, exercise_name: "Pull Up", weight_kg: 0, reps: 8 }),
            makeSet({ id: 2, exercise_name: "Pull Up", set_number: 2, reps: 8, weight_kg: 0 }),
            makeSet({ id: 3, exercise_name: "Pull Up", set_number: 3, reps: 8, weight_kg: 0 }),
          ],
        }),
        makeExercise({
          name: "Dip",
          order_index: 1,
          superset_group_id: 1,
          sets: [
            makeSet({ id: 4, exercise_name: "Dip", weight_kg: 0, reps: 10 }),
            makeSet({ id: 5, exercise_name: "Dip", set_number: 2, reps: 10, weight_kg: 0 }),
            makeSet({ id: 6, exercise_name: "Dip", set_number: 3, reps: 10, weight_kg: 0 }),
          ],
        }),
        makeExercise({
          name: "Plank",
          order_index: 2,
          superset_group_id: null,
        }),
      ],
    };
    fetchStrengthSessionOptional.mockResolvedValue(session);

    renderRoute("2026-05-24");

    await waitFor(() =>
      expect(screen.getByText("Pull Up")).toBeInTheDocument(),
    );
    const brackets = screen.getAllByTestId("superset-bracket");
    expect(brackets).toHaveLength(1);
    // The bracket should contain both grouped exercises.
    const bracket = brackets[0];
    expect(bracket).toHaveTextContent("Pull Up");
    expect(bracket).toHaveTextContent("Dip");
    // Standalone Plank is not inside the bracket.
    expect(bracket).not.toHaveTextContent("Plank");
    expect(screen.getByText("Plank")).toBeInTheDocument();
    // Rounds = min set count across grouped exercises = 3.
    expect(bracket).toHaveTextContent(/3 rounds/);
  });

  it("renders the 404 empty state when no session exists", async () => {
    fetchStrengthSessionOptional.mockResolvedValue(null);
    renderRoute("2026-05-24");
    await waitFor(() =>
      expect(
        screen.getByText("No strength session on this date."),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /back to history/i }),
    ).toBeInTheDocument();
  });
});
