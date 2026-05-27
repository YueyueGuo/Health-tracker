import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchActivity } from "./activities";

describe("fetchActivity URL construction", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function stubOkFetch(): ReturnType<typeof vi.fn> {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({}), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("appends ?units=imperial when units='imperial' is passed", async () => {
    const fetchMock = stubOkFetch();
    await fetchActivity(42, "apple_health", "imperial");
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/api/activities/42");
    expect(url).toContain("source=apple_health");
    expect(url).toContain("units=imperial");
  });

  it("appends ?units=metric when units='metric' is passed", async () => {
    const fetchMock = stubOkFetch();
    await fetchActivity(42, "apple_health", "metric");
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("units=metric");
  });

  it("omits the units param when units is undefined or null", async () => {
    const fetchMock = stubOkFetch();
    await fetchActivity(42, "strava");
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).not.toContain("units=");
    expect(url).toContain("source=strava");
  });

  it("constructs a clean URL when neither source nor units is provided", async () => {
    const fetchMock = stubOkFetch();
    await fetchActivity(42);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/api/activities/42");
  });
});
