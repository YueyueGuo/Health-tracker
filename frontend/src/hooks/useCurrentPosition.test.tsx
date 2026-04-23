import { renderHook, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useCurrentPosition } from "./useCurrentPosition";

describe("useCurrentPosition", () => {
  afterEach(() => {
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: undefined,
    });
    vi.restoreAllMocks();
  });

  it("reports when geolocation is unavailable", () => {
    const { result } = renderHook(() => useCurrentPosition());

    act(() => {
      result.current.requestPosition();
    });

    expect(result.current.error).toBe("Geolocation is not available in this browser.");
    expect(result.current.fetching).toBe(false);
    expect(result.current.coords).toBeNull();
  });

  it("stores coordinates on success", () => {
    const getCurrentPosition = vi.fn(
      (
        success: PositionCallback,
        _error?: PositionErrorCallback | null,
        _options?: PositionOptions
      ) => {
        success({
          coords: {
            latitude: 39.7392,
            longitude: -104.9903,
            accuracy: 1,
            altitude: null,
            altitudeAccuracy: null,
            heading: null,
            speed: null,
            toJSON: () => ({}),
          },
          timestamp: Date.now(),
          toJSON: () => ({}),
        } as GeolocationPosition);
      }
    );
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: { getCurrentPosition },
    });

    const { result } = renderHook(() => useCurrentPosition());

    act(() => {
      result.current.requestPosition();
    });

    expect(getCurrentPosition).toHaveBeenCalled();
    expect(result.current.coords).toEqual({ lat: 39.7392, lng: -104.9903 });
    expect(result.current.error).toBeNull();
    expect(result.current.fetching).toBe(false);
  });

  it("stores geolocation errors", () => {
    const getCurrentPosition = vi.fn(
      (
        _success: PositionCallback,
        error?: PositionErrorCallback | null,
        _options?: PositionOptions
      ) => {
        error?.({
          code: 1,
          message: "Permission denied",
          PERMISSION_DENIED: 1,
          POSITION_UNAVAILABLE: 2,
          TIMEOUT: 3,
        });
      }
    );
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: { getCurrentPosition },
    });

    const { result } = renderHook(() => useCurrentPosition());

    act(() => {
      result.current.requestPosition();
    });

    expect(result.current.error).toBe("Permission denied");
    expect(result.current.coords).toBeNull();
    expect(result.current.fetching).toBe(false);
  });
});
