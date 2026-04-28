import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { BottomNav } from "./BottomNav";

describe("BottomNav", () => {
  it("links the user tab to the profile route", () => {
    render(
      <MemoryRouter initialEntries={["/profile"]}>
        <BottomNav />
      </MemoryRouter>
    );

    expect(screen.getByRole("link", { name: /Profile/ })).toHaveAttribute(
      "href",
      "/profile"
    );
  });
});
