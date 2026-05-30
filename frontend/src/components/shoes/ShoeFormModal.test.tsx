import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/shoes", () => ({
  createShoe: vi.fn(),
  patchShoe: vi.fn(),
}));

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: "metric" }),
}));

import ShoeFormModal from "./ShoeFormModal";

describe("ShoeFormModal", () => {
  it("does not render when closed", () => {
    render(
      <ShoeFormModal open={false} onClose={vi.fn()} onSaved={vi.fn()} />,
    );
    expect(screen.queryByTestId("shoe-form-modal")).not.toBeInTheDocument();
  });

  // Regression: the bottom sheet rendered flush against the viewport
  // bottom, so its scroll area and Save button were hidden behind the
  // fixed BottomNav (h-16 = 4rem). The mobile sheet must reserve space
  // for the nav and cap its height so the form stays fully reachable.
  it("clears the fixed bottom nav on mobile so the Save button stays visible", () => {
    render(<ShoeFormModal open onClose={vi.fn()} onSaved={vi.fn()} />);
    const overlay = screen.getByTestId("shoe-form-modal");
    // Bottom inset equal to the nav height (+ safe area) keeps the sheet
    // above the nav instead of underneath it.
    expect(overlay.className).toContain(
      "pb-[calc(4rem+env(safe-area-inset-bottom))]",
    );

    const card = overlay.firstElementChild as HTMLElement;
    // Height is capped to the space left above the nav; a tall form then
    // scrolls internally rather than overflowing under the nav.
    expect(card.className).toContain("max-h-[calc(100vh-5rem)]");
    expect(card.className).toContain("flex");
    expect(card.className).toContain("flex-col");
  });
});
