import { describe, expect, it } from "vitest";
import {
  formatPercentUsed,
  formatShoeDistance,
  metersToInput,
  parseDistanceInput,
  progressTone,
  unitLabel,
} from "./shoeFormatting";

describe("formatShoeDistance", () => {
  it("renders meters in miles for imperial users", () => {
    expect(formatShoeDistance(1609.344, "imperial")).toBe("1 mi");
    expect(formatShoeDistance(8046.72, "imperial")).toBe("5 mi"); // 5 miles
  });
  it("renders meters in km for metric users", () => {
    expect(formatShoeDistance(1000, "metric")).toBe("1 km");
    expect(formatShoeDistance(8000, "metric")).toBe("8 km");
  });
  it("handles null", () => {
    expect(formatShoeDistance(null, "metric")).toBe("—");
  });
});

describe("formatPercentUsed", () => {
  it("returns em-dash for null", () => {
    expect(formatPercentUsed(null)).toBe("—");
  });
  it("rounds to the nearest integer", () => {
    expect(formatPercentUsed(42.4)).toBe("42%");
    expect(formatPercentUsed(42.5)).toBe("43%");
  });
  it("passes through over-100 readings (overdue)", () => {
    expect(formatPercentUsed(123)).toBe("123%");
  });
});

describe("progressTone", () => {
  it("ok below 80", () => {
    expect(progressTone(0)).toBe("ok");
    expect(progressTone(79.9)).toBe("ok");
  });
  it("warn in [80, 100)", () => {
    expect(progressTone(80)).toBe("warn");
    expect(progressTone(99.9)).toBe("warn");
  });
  it("danger at >= 100", () => {
    expect(progressTone(100)).toBe("danger");
    expect(progressTone(150)).toBe("danger");
  });
  it("ok for null (no target)", () => {
    expect(progressTone(null)).toBe("ok");
  });
});

describe("parseDistanceInput", () => {
  it("returns null on empty input (clear target)", () => {
    expect(parseDistanceInput("", "metric")).toBeNull();
    expect(parseDistanceInput("   ", "metric")).toBeNull();
  });
  it("returns undefined for non-numeric or non-positive input", () => {
    expect(parseDistanceInput("abc", "metric")).toBeUndefined();
    expect(parseDistanceInput("-5", "metric")).toBeUndefined();
    expect(parseDistanceInput("0", "metric")).toBeUndefined();
  });
  it("converts km to meters for metric users", () => {
    expect(parseDistanceInput("500", "metric")).toBe(500000);
  });
  it("converts miles to meters for imperial users", () => {
    expect(parseDistanceInput("300", "imperial")).toBeCloseTo(482803.2, 1);
  });
});

describe("metersToInput", () => {
  it("returns empty string for null", () => {
    expect(metersToInput(null, "metric")).toBe("");
  });
  it("converts meters → km for metric", () => {
    expect(metersToInput(500000, "metric")).toBe("500");
  });
  it("converts meters → mi for imperial", () => {
    // 500 mi → ~804672 m; back to mi is 500 (rounded to 2dp).
    expect(metersToInput(500 * 1609.344, "imperial")).toBe("500");
  });
});

describe("unitLabel", () => {
  it("returns the active unit suffix", () => {
    expect(unitLabel("metric")).toBe("km");
    expect(unitLabel("imperial")).toBe("mi");
  });
});
