import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ShoeProgressBar from "./ShoeProgressBar";

describe("ShoeProgressBar", () => {
  it("applies the 'ok' tone below 80%", () => {
    render(<ShoeProgressBar percent={42} />);
    const bar = screen.getByTestId("shoe-progress");
    expect(bar.getAttribute("data-tone")).toBe("ok");
  });

  it("applies the 'warn' tone in [80, 100)", () => {
    render(<ShoeProgressBar percent={85} />);
    const bar = screen.getByTestId("shoe-progress");
    expect(bar.getAttribute("data-tone")).toBe("warn");
  });

  it("applies the 'danger' tone at >= 100%", () => {
    render(<ShoeProgressBar percent={105} />);
    const bar = screen.getByTestId("shoe-progress");
    expect(bar.getAttribute("data-tone")).toBe("danger");
  });

  it("renders a no-target placeholder when percent is null", () => {
    render(<ShoeProgressBar percent={null} />);
    expect(screen.getByTestId("shoe-progress-no-target")).toBeInTheDocument();
    expect(screen.queryByTestId("shoe-progress")).not.toBeInTheDocument();
  });

  it("renders the percent label by default and hides it in compact mode", () => {
    const { rerender } = render(<ShoeProgressBar percent={42} />);
    expect(screen.getByText("42%")).toBeInTheDocument();
    rerender(<ShoeProgressBar percent={42} compact />);
    expect(screen.queryByText("42%")).not.toBeInTheDocument();
  });
});
