import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import GpsLocationForm from "./GpsLocationForm";

vi.mock("../../hooks/useCurrentPosition", () => ({
  useCurrentPosition: vi.fn(),
}));

import { useCurrentPosition } from "../../hooks/useCurrentPosition";

const mockedUseCurrentPosition = vi.mocked(useCurrentPosition);

describe("GpsLocationForm", () => {
  it("requests current location when idle", () => {
    const requestPosition = vi.fn();
    mockedUseCurrentPosition.mockReturnValue({
      coords: null,
      error: null,
      fetching: false,
      requestPosition,
      reset: vi.fn(),
    });

    render(
      <GpsLocationForm
        intro="Use GPS"
        onCancel={vi.fn()}
        onPick={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Get current location" }));

    expect(requestPosition).toHaveBeenCalled();
    expect(screen.getByText("Use GPS")).toBeInTheDocument();
  });

  it("submits picked coordinates with a trimmed name", () => {
    const onPick = vi.fn();
    const reset = vi.fn();
    mockedUseCurrentPosition.mockReturnValue({
      coords: { lat: 39.7392, lng: -104.9903 },
      error: null,
      fetching: false,
      requestPosition: vi.fn(),
      reset,
    });

    render(<GpsLocationForm onCancel={vi.fn()} onPick={onPick} />);

    fireEvent.change(screen.getByPlaceholderText("Name this location (e.g. Home)"), {
      target: { value: "  Home gym  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onPick).toHaveBeenCalledWith("Home gym", 39.7392, -104.9903);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(reset).toHaveBeenCalled();
  });

  it("renders hook errors", () => {
    mockedUseCurrentPosition.mockReturnValue({
      coords: null,
      error: "Permission denied",
      fetching: false,
      requestPosition: vi.fn(),
      reset: vi.fn(),
    });

    render(<GpsLocationForm onCancel={vi.fn()} onPick={vi.fn()} />);

    expect(screen.getByText("Permission denied")).toBeInTheDocument();
  });
});
