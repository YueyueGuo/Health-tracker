import { describe, expect, it } from "vitest";
import { shouldPersistAppQuery } from "./queryCache";

function query(queryKey: readonly unknown[], status = "success") {
  return { queryKey, state: { status } };
}

describe("shouldPersistAppQuery", () => {
  it("persists successful health data queries", () => {
    expect(shouldPersistAppQuery(query(["activities", "history"]))).toBe(true);
    expect(shouldPersistAppQuery(query(["sleep", "sessions", 30]))).toBe(true);
  });

  it("does not persist sync/debug queries", () => {
    expect(shouldPersistAppQuery(query(["sync", "status"]))).toBe(false);
  });

  it("does not persist failed, pending, or malformed queries", () => {
    expect(shouldPersistAppQuery(query(["activities"], "error"))).toBe(false);
    expect(shouldPersistAppQuery(query(["activities"], "pending"))).toBe(false);
    expect(shouldPersistAppQuery(query([42]))).toBe(false);
  });
});
