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
}));

vi.mock("../api/activities", () => ({
  fetchActivities: vi.fn(),
}));

import StrengthEntry from "./StrengthEntry";
import { fetchActivities } from "../api/activities";
import { createStrengthSession, fetchStrengthExercises } from "../api/strength";

const mockedCreateStrengthSession = vi.mocked(createStrengthSession);
const mockedFetchStrengthExercises = vi.mocked(fetchStrengthExercises);
const mockedFetchActivities = vi.mocked(fetchActivities);

describe("StrengthEntry", () => {
  beforeEach(() => {
    mockedFetchStrengthExercises.mockResolvedValue(["Squat"]);
    mockedFetchActivities.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows a fallback save error when submission fails with a non-Error value", async () => {
    mockedCreateStrengthSession.mockRejectedValue("bad payload");

    render(<StrengthEntry />);

    fireEvent.change(screen.getByPlaceholderText("Exercise"), {
      target: { value: "Squat" },
    });
    fireEvent.change(screen.getAllByRole("spinbutton")[1], {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save session/i }));

    await waitFor(() => expect(mockedCreateStrengthSession).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Failed to save session")).toBeInTheDocument();
    expect(mockedNavigate).not.toHaveBeenCalled();
  });
});
