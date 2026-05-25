// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SupersetBracket } from "./SupersetBracket";

describe("SupersetBracket", () => {
  it("wraps its children with the brand-green left border", () => {
    render(
      <SupersetBracket exerciseCount={2} rounds={3}>
        <div>Child A</div>
        <div>Child B</div>
      </SupersetBracket>,
    );
    const bracket = screen.getByTestId("superset-bracket");
    expect(bracket.className).toContain("border-l-2");
    expect(bracket.className).toContain("border-l-brand-green");
    expect(screen.getByText("Child A")).toBeInTheDocument();
    expect(screen.getByText("Child B")).toBeInTheDocument();
  });

  it("renders the exercise count and rounds in the label", () => {
    render(
      <SupersetBracket exerciseCount={2} rounds={3}>
        <div>only child</div>
      </SupersetBracket>,
    );
    // Pluralization: "2 exercises · 3 rounds"
    expect(screen.getByText(/2 exercises/)).toBeInTheDocument();
    expect(screen.getByText(/3 rounds/)).toBeInTheDocument();
  });

  it("uses singular labels when count is 1", () => {
    render(
      <SupersetBracket exerciseCount={1} rounds={1}>
        <div>x</div>
      </SupersetBracket>,
    );
    expect(screen.getByText(/1 exercise/)).toBeInTheDocument();
    expect(screen.getByText(/1 round/)).toBeInTheDocument();
  });
});
