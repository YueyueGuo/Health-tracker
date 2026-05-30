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

  it("renders a clickable button when an onClick is provided", () => {
    render(
      <HistoryEventCard
        event={makeEvent({ title: "Strava Run", navigateTo: "/activities/1" })}
        onClick={() => {}}
      />
    );
    expect(
      screen.getByRole("button", { name: "Open Strava Run" })
    ).toBeInTheDocument();
  });

  it("renders the HR-linked indicator only when hrLinked is true and type is Strength", () => {
    const { unmount } = render(
      <HistoryEventCard
        event={makeEvent({
          id: "strength-2026-05-25",
          type: "Strength",
          title: "Strength Session",
          hrLinked: true,
          navigateTo: "/strength/session/2026-05-25",
        })}
      />
    );
    expect(screen.getByTestId("hr-linked-indicator")).toBeInTheDocument();
    unmount();

    const { unmount: u2 } = render(
      <HistoryEventCard
        event={makeEvent({
          id: "strength-2026-05-25",
          type: "Strength",
          title: "Strength Session",
          hrLinked: false,
          navigateTo: "/strength/session/2026-05-25",
        })}
      />
    );
    expect(
      screen.queryByTestId("hr-linked-indicator")
    ).not.toBeInTheDocument();
    u2();

    // Non-strength events: indicator should never render even if the flag is set.
    render(
      <HistoryEventCard
        event={makeEvent({
          id: "activity-99",
          type: "Run",
          title: "Run",
          hrLinked: true,
        })}
      />
    );
    expect(
      screen.queryByTestId("hr-linked-indicator")
    ).not.toBeInTheDocument();
  });

  it("renders the type tag but no flag chips when classificationType is set", () => {
    render(
      <HistoryEventCard
        event={makeEvent({
          title: "Track Workout",
          classificationType: "intervals",
          classificationFlags: ["has_speed_component", "is_long"],
          sourceBadge: "strava",
        })}
      />
    );
    expect(screen.getByText("intervals")).toBeInTheDocument();
    // Only the type label shows — the cryptic flag icons (⚡, L, …) must not.
    expect(screen.queryByText("⚡")).not.toBeInTheDocument();
    expect(screen.queryByText("L")).not.toBeInTheDocument();
  });

  it("renders no type tag (and does not crash) when classificationType is null", () => {
    render(
      <HistoryEventCard
        event={makeEvent({
          title: "Apple Workout",
          classificationType: null,
          classificationFlags: null,
          sourceBadge: "apple",
        })}
      />
    );
    expect(screen.getByRole("heading", { name: "Apple Workout" })).toBeInTheDocument();
    // No classification text and, importantly, no fallback em-dash badge.
    expect(screen.queryByText("intervals")).not.toBeInTheDocument();
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("renders the type tag alongside the source pill", () => {
    render(
      <HistoryEventCard
        event={makeEvent({
          title: "Tempo Run",
          classificationType: "tempo",
          sourceBadge: "strava",
        })}
      />
    );
    expect(screen.getByText("tempo")).toBeInTheDocument();
    expect(screen.getByTestId("source-badge-strava")).toBeInTheDocument();
  });

  it("renders no clickable container for Apple-only workouts (no onClick)", () => {
    // Mirrors the wiring in History.tsx: when `navigateTo` is null, the
    // page does not pass an `onClick`. The card must then render as a
    // non-interactive container — no button role.
    render(
      <HistoryEventCard
        event={makeEvent({
          title: "Apple Run",
          sourceBadge: "apple",
          navigateTo: null,
        })}
      />
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Apple Run" })).toBeInTheDocument();
  });
});
