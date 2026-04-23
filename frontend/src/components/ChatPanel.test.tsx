import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/chat", () => ({
  askQuestion: vi.fn(),
  fetchAvailableModels: vi.fn(),
}));

import ChatPanel from "./ChatPanel";
import { askQuestion, fetchAvailableModels } from "../api/chat";

const mockedAskQuestion = vi.mocked(askQuestion);
const mockedFetchAvailableModels = vi.mocked(fetchAvailableModels);
const originalScrollIntoView = Element.prototype.scrollIntoView;

describe("ChatPanel", () => {
  beforeEach(() => {
    mockedFetchAvailableModels.mockResolvedValue({ models: ["gpt-4o"] });
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    Element.prototype.scrollIntoView = originalScrollIntoView;
    vi.clearAllMocks();
  });

  it("shows a fallback error message when chat fails with a non-Error value", async () => {
    mockedAskQuestion.mockRejectedValue("network down");

    render(<ChatPanel />);

    fireEvent.change(screen.getByPlaceholderText(/ask about your workouts/i), {
      target: { value: "How am I doing?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(mockedAskQuestion).toHaveBeenCalledWith("How am I doing?", undefined)
    );
    expect(await screen.findByText("Error: Request failed")).toBeInTheDocument();
  });
});
