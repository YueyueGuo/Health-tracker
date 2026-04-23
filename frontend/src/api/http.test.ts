import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, fetchJson, fetchOptionalJson } from "./http";

describe("http helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sets JSON headers and parses a successful response", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      expect(headers.get("Accept")).toBe("application/json");
      expect(headers.get("Content-Type")).toBe("application/json");
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchJson<{ ok: boolean }>("/test", {
      method: "POST",
      body: JSON.stringify({ hello: "world" }),
    });

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/test",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("returns undefined for 204/205 responses", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));

    const result = await fetchJson<void>("/empty");

    expect(result).toBeUndefined();
  });

  it("surfaces FastAPI detail strings in ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "No weather snapshot for this activity" }), {
            status: 404,
            statusText: "Not Found",
          })
      )
    );

    await expect(fetchJson("/weather")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      message: "No weather snapshot for this activity",
    });
  });

  it("returns null from fetchOptionalJson for configured optional statuses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("missing", { status: 404, statusText: "Not Found" }))
    );

    await expect(fetchOptionalJson("/optional")).resolves.toBeNull();
  });

  it("rethrows non-optional ApiErrors from fetchOptionalJson", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("boom", { status: 500, statusText: "Server Error" }))
    );

    await expect(fetchOptionalJson("/optional")).rejects.toMatchObject({
      status: 500,
      message: "boom",
    });
  });
});
