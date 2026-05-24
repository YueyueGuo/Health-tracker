import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HistoryEventCard } from "./HistoryEventCard";
import type { HistoryEvent } from "../../lib/historyEvents";

function makeEvent(over: Partial<HistoryEvent> = {}): HistoryEvent {
  return {
    id: "activity-1",
    category: "Workout",
    type: "Run",
    title: "Morning Run",
    timestamp: "2026-05-24T09:00:00",
    metrics: [
      { label: "Distance", value: "5.0 mi" },
      { label: "Time", value: "45m" },
    ],
    navigateTo: "/activities/1",
    ...over,
  };
}

describe("HistoryEventCard", () => {
  it("renders the Apple badge when sourceBadge is apple", () => {
    render(<HistoryEventCard event={makeEvent({ sourceBadge: "apple" })} />);
    expect(screen.getByTestId("source-badge-apple")).toBeInTheDocument();
    expect(screen.getByText("Apple")).toBeInTheDocument();
    expect(screen.queryByTestId("source-badge-strava")).not.toBeInTheDocument();
  });

  it("renders the Strava badge when sourceBadge is strava", () => {
    render(<HistoryEventCard event={makeEvent({ sourceBadge: "strava" })} />);
    expect(screen.getByTestId("source-badge-strava")).toBeInTheDocument();
    expect(screen.getByText("Strava")).toBeInTheDocument();
    expect(screen.queryByTestId("source-badge-apple")).not.toBeInTheDocument();
  });

  it("renders no source badge when sourceBadge is undefined", () => {
    render(<HistoryEventCard event={makeEvent({ sourceBadge: undefined })} />);
    expect(screen.queryByTestId("source-badge-apple")).not.toBeInTheDocument();
    expect(screen.queryByTestId("source-badge-strava")).not.toBeInTheDocument();
  });

  it("still renders the event title alongside the badge", () => {
    render(
      <HistoryEventCard
        event={makeEvent({ title: "Trail Run", sourceBadge: "strava" })}
      />
    );
    expect(screen.getByRole("heading", { name: "Trail Run" })).toBeInTheDocument();
    expect(screen.getByTestId("source-badge-strava")).toBeInTheDocument();
  });
});
