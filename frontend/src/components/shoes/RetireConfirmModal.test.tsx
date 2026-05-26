import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RetireConfirmModal from "./RetireConfirmModal";

describe("RetireConfirmModal", () => {
  it("does not render when closed", () => {
    render(
      <RetireConfirmModal
        open={false}
        shoeName="Vaporfly"
        onClose={vi.fn()}
        onConfirm={vi.fn().mockResolvedValue(undefined)}
      />,
    );
    expect(screen.queryByTestId("retire-confirm-modal")).not.toBeInTheDocument();
  });

  it("calls onConfirm when the user confirms", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(
      <RetireConfirmModal
        open
        shoeName="Vaporfly"
        onClose={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Retire" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
  });

  it("calls onClose when the user cancels without confirming", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <RetireConfirmModal
        open
        shoeName="Vaporfly"
        onClose={onClose}
        onConfirm={onConfirm}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("surfaces errors from onConfirm without closing the modal", async () => {
    const onConfirm = vi.fn().mockRejectedValue(new Error("Network down"));
    render(
      <RetireConfirmModal
        open
        shoeName="Vaporfly"
        onClose={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Retire" }));
    await screen.findByText("Network down");
    // Modal still mounted — the user can retry.
    expect(screen.getByTestId("retire-confirm-modal")).toBeInTheDocument();
  });
});
