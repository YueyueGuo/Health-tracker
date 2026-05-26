import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/shoes", () => ({
  createShoe: vi.fn(),
  listShoes: vi.fn(),
}));

vi.mock("../../api/activities", () => ({
  patchActivityShoe: vi.fn(),
}));

vi.mock("../../hooks/useUnits", () => ({
  useUnits: () => ({ units: "metric" }),
}));

import { renderWithQuery } from "../../test/renderWithQuery";
import ShoeSelector from "./ShoeSelector";
import { createShoe, listShoes, type Shoe } from "../../api/shoes";
import { patchActivityShoe } from "../../api/activities";

const mockedListShoes = vi.mocked(listShoes);
const mockedCreateShoe = vi.mocked(createShoe);
const mockedPatchActivityShoe = vi.mocked(patchActivityShoe);

function shoe(over: Partial<Shoe> = {}): Shoe {
  return {
    id: 1,
    name: "Vaporfly",
    brand: null,
    model: null,
    shoe_type: "race",
    status: "active",
    total_usable_distance_m: 400000,
    purchased_on: null,
    retired_at: null,
    notes: null,
    created_at: "2026-01-10T00:00:00Z",
    updated_at: "2026-01-10T00:00:00Z",
    cumulative_distance_m: 100000,
    percent_used: 25,
    ...over,
  };
}

describe("ShoeSelector", () => {
  beforeEach(() => {
    mockedPatchActivityShoe.mockResolvedValue({
      id: 42,
      source: "strava",
      shoe_id: null,
    });
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the current shoe id by default", async () => {
    mockedListShoes.mockResolvedValue([shoe(), shoe({ id: 2, name: "Pegasus" })]);
    renderWithQuery(
      <ShoeSelector
        activityId={42}
        source="strava"
        currentShoeId={2}
        onChange={vi.fn()}
      />,
    );
    const select = (await screen.findByLabelText(
      "Tag a shoe",
    )) as HTMLSelectElement;
    expect(select.value).toBe("2");
  });

  it("renders '— None —' when activity.shoe_id is null", async () => {
    mockedListShoes.mockResolvedValue([shoe()]);
    renderWithQuery(
      <ShoeSelector
        activityId={42}
        source="strava"
        currentShoeId={null}
        onChange={vi.fn()}
      />,
    );
    const select = (await screen.findByLabelText(
      "Tag a shoe",
    )) as HTMLSelectElement;
    expect(select.value).toBe("");
  });

  it("calls patchActivityShoe when the user picks a shoe", async () => {
    mockedListShoes.mockResolvedValue([shoe(), shoe({ id: 2, name: "Pegasus" })]);
    const onChange = vi.fn();
    renderWithQuery(
      <ShoeSelector
        activityId={42}
        source="strava"
        currentShoeId={null}
        onChange={onChange}
      />,
    );
    const select = (await screen.findByLabelText(
      "Tag a shoe",
    )) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "2" } });
    await waitFor(() =>
      expect(mockedPatchActivityShoe).toHaveBeenCalledWith(42, 2, "strava"),
    );
    await waitFor(() => expect(onChange).toHaveBeenCalled());
  });

  it("calls patchActivityShoe with shoe_id=null when the user picks None", async () => {
    mockedListShoes.mockResolvedValue([shoe()]);
    renderWithQuery(
      <ShoeSelector
        activityId={42}
        source="strava"
        currentShoeId={1}
        onChange={vi.fn()}
      />,
    );
    const select = (await screen.findByLabelText(
      "Tag a shoe",
    )) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "" } });
    await waitFor(() =>
      expect(mockedPatchActivityShoe).toHaveBeenCalledWith(42, null, "strava"),
    );
  });

  it("does not include retired shoes in the dropdown options (active-only fetch)", async () => {
    // listShoes("active") is the only call made — we assert that here.
    mockedListShoes.mockResolvedValue([shoe()]);
    renderWithQuery(
      <ShoeSelector
        activityId={42}
        source="strava"
        currentShoeId={null}
        onChange={vi.fn()}
      />,
    );
    await screen.findByLabelText("Tag a shoe");
    expect(mockedListShoes).toHaveBeenCalledWith("active");
  });

  it("shows the 'Add a shoe' affordance when listShoes returns []", async () => {
    mockedListShoes.mockResolvedValue([]);
    renderWithQuery(
      <ShoeSelector
        activityId={42}
        source="strava"
        currentShoeId={null}
        onChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByRole("button", { name: "+ Add a shoe" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Tag a shoe")).not.toBeInTheDocument();
  });

  it("empty-state inline create: chains createShoe + patchActivityShoe and invalidates caches", async () => {
    mockedListShoes.mockResolvedValue([]);
    mockedCreateShoe.mockResolvedValue(shoe({ id: 9, name: "Brand new" }));
    const onChange = vi.fn();
    renderWithQuery(
      <ShoeSelector
        activityId={42}
        source="strava"
        currentShoeId={null}
        onChange={onChange}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "+ Add a shoe" }),
    );
    fireEvent.change(screen.getByPlaceholderText(/Vaporfly 3 — blue/), {
      target: { value: "Brand new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save & tag" }));
    await waitFor(() =>
      expect(mockedCreateShoe).toHaveBeenCalledWith(
        expect.objectContaining({ name: "Brand new" }),
      ),
    );
    await waitFor(() =>
      expect(mockedPatchActivityShoe).toHaveBeenCalledWith(42, 9, "strava"),
    );
    await waitFor(() => expect(onChange).toHaveBeenCalled());
  });

  it("keeps the inline form open when createShoe rejects", async () => {
    mockedListShoes.mockResolvedValue([]);
    mockedCreateShoe.mockRejectedValue(new Error("Server is grumpy"));
    renderWithQuery(
      <ShoeSelector
        activityId={42}
        source="strava"
        currentShoeId={null}
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "+ Add a shoe" }),
    );
    fireEvent.change(screen.getByPlaceholderText(/Vaporfly 3 — blue/), {
      target: { value: "Brand new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save & tag" }));
    await screen.findByText("Server is grumpy");
    // Tag never happened.
    expect(mockedPatchActivityShoe).not.toHaveBeenCalled();
  });

  it("surfaces the partial-failure copy when the tag PATCH fails after a successful create", async () => {
    mockedListShoes.mockResolvedValue([]);
    mockedCreateShoe.mockResolvedValue(shoe({ id: 9, name: "Brand new" }));
    mockedPatchActivityShoe.mockRejectedValue(
      new Error("Couldn't reach server"),
    );
    renderWithQuery(
      <ShoeSelector
        activityId={42}
        source="strava"
        currentShoeId={null}
        onChange={vi.fn()}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "+ Add a shoe" }),
    );
    fireEvent.change(screen.getByPlaceholderText(/Vaporfly 3 — blue/), {
      target: { value: "Brand new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save & tag" }));
    await screen.findByText(/Created Brand new but failed to tag/);
  });
});
