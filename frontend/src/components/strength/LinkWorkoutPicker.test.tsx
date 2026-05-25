// @vitest-environment jsdom
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import LinkWorkoutPicker from "./LinkWorkoutPicker";
import { ApiError } from "../../api/http";

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: "imperial", setUnits: () => {}, toggle: () => {} }),
}));

const fetchLinkCandidatesMock = vi.fn();
const linkWorkoutMock = vi.fn();

vi.mock("../../api/strength", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../api/strength")>();
  return {
    ...actual,
    fetchLinkCandidates: (date: string) => fetchLinkCandidatesMock(date),
    linkWorkout: (date: string, body: unknown) =>
      linkWorkoutMock(date, body),
  };
});

function fakeStrava() {
  return {
    source: "strava" as const,
    ref_id: 11,
    name: "Garage lift",
    sport: "WeightTraining",
    start_local: "2026-05-25T17:30:00",
    duration_s: 3000,
    avg_hr: 128,
    max_hr: 160,
    distance_m: null,
    hr_stream_available: true,
  };
}

function fakeApple() {
  return {
    source: "apple_health" as const,
    ref_id: 22,
    name: "Apple Workout",
    sport: "strength",
    start_local: "2026-05-25T07:00:00",
    duration_s: 2400,
    avg_hr: 121,
    max_hr: 150,
    distance_m: null,
    hr_stream_available: false,
  };
}

beforeEach(() => {
  fetchLinkCandidatesMock.mockReset();
  linkWorkoutMock.mockReset();
});

describe("LinkWorkoutPicker", () => {
  it("renders both source badges for the loaded candidates", async () => {
    fetchLinkCandidatesMock.mockResolvedValue([fakeStrava(), fakeApple()]);
    render(
      <LinkWorkoutPicker
        date="2026-05-25"
        open
        onClose={vi.fn()}
        onLinked={vi.fn()}
      />
    );
    await waitFor(() =>
      expect(screen.getByText("Garage lift")).toBeInTheDocument()
    );
    expect(screen.getByText("Apple Workout")).toBeInTheDocument();
    expect(screen.getByTestId("source-badge-strava")).toBeInTheDocument();
    expect(screen.getByTestId("source-badge-apple")).toBeInTheDocument();
  });

  it("shows the empty state when no candidates are returned", async () => {
    fetchLinkCandidatesMock.mockResolvedValue([]);
    render(
      <LinkWorkoutPicker
        date="2026-05-25"
        open
        onClose={vi.fn()}
        onLinked={vi.fn()}
      />
    );
    await waitFor(() =>
      expect(screen.getByTestId("link-picker-empty")).toBeInTheDocument()
    );
    expect(
      screen.getByText(/no device workouts found within ±1 day/i)
    ).toBeInTheDocument();
  });

  it("calls linkWorkout, onLinked and onClose on a successful pick", async () => {
    fetchLinkCandidatesMock.mockResolvedValue([fakeStrava()]);
    linkWorkoutMock.mockResolvedValue({});
    const onLinked = vi.fn();
    const onClose = vi.fn();
    render(
      <LinkWorkoutPicker
        date="2026-05-25"
        open
        onClose={onClose}
        onLinked={onLinked}
      />
    );
    const row = await screen.findByTestId("link-picker-row-strava:11");
    fireEvent.click(row);
    await waitFor(() => expect(linkWorkoutMock).toHaveBeenCalledTimes(1));
    expect(linkWorkoutMock).toHaveBeenCalledWith("2026-05-25", {
      source: "strava",
      ref_id: 11,
    });
    expect(onLinked).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("surfaces a 409 inline and keeps the picker open", async () => {
    fetchLinkCandidatesMock.mockResolvedValue([fakeStrava()]);
    const resp = new Response(null, { status: 409, statusText: "Conflict" });
    linkWorkoutMock.mockRejectedValue(new ApiError(resp, null));
    const onLinked = vi.fn();
    const onClose = vi.fn();
    render(
      <LinkWorkoutPicker
        date="2026-05-25"
        open
        onClose={onClose}
        onLinked={onLinked}
      />
    );
    const row = await screen.findByTestId("link-picker-row-strava:11");
    fireEvent.click(row);
    await waitFor(() =>
      expect(screen.getByTestId("link-picker-error")).toBeInTheDocument()
    );
    expect(
      screen.getByText(/already linked to another session/i)
    ).toBeInTheDocument();
    expect(onLinked).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes after a 502 because the link is persisted server-side", async () => {
    fetchLinkCandidatesMock.mockResolvedValue([fakeStrava()]);
    const resp = new Response(null, {
      status: 502,
      statusText: "Bad Gateway",
    });
    linkWorkoutMock.mockRejectedValue(new ApiError(resp, null));
    const onLinked = vi.fn();
    const onClose = vi.fn();
    render(
      <LinkWorkoutPicker
        date="2026-05-25"
        open
        onClose={onClose}
        onLinked={onLinked}
      />
    );
    const row = await screen.findByTestId("link-picker-row-strava:11");
    fireEvent.click(row);
    await waitFor(() => expect(onLinked).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
