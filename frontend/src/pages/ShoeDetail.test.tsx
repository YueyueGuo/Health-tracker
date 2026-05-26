import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/shoes", () => ({
  getShoe: vi.fn(),
  listShoeActivities: vi.fn(),
  patchShoe: vi.fn(),
  retireShoe: vi.fn(),
  unretireShoe: vi.fn(),
}));

vi.mock("../hooks/useUnits", () => ({
  useUnits: () => ({ units: "metric" }),
}));

let routeId = "1";
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return {
    ...actual,
    useParams: () => ({ id: routeId }),
  };
});

import { renderWithQuery } from "../test/renderWithQuery";
import ShoeDetail from "./ShoeDetail";
import {
  getShoe,
  listShoeActivities,
  patchShoe,
  retireShoe,
  unretireShoe,
  type ShoeDetail as ShoeDetailType,
} from "../api/shoes";

const mockedGetShoe = vi.mocked(getShoe);
const mockedListActs = vi.mocked(listShoeActivities);
const mockedPatchShoe = vi.mocked(patchShoe);
const mockedRetire = vi.mocked(retireShoe);
const mockedUnretire = vi.mocked(unretireShoe);

function detail(over: Partial<ShoeDetailType> = {}): ShoeDetailType {
  return {
    id: 1,
    name: "Vaporfly",
    brand: "Nike",
    model: "ZoomX",
    shoe_type: "race",
    status: "active",
    total_usable_distance_m: 400000,
    purchased_on: "2026-01-10",
    retired_at: null,
    notes: "Race-day only",
    created_at: "2026-01-10T00:00:00Z",
    updated_at: "2026-01-10T00:00:00Z",
    cumulative_distance_m: 100000,
    percent_used: 25,
    tagged_activity_count: 3,
    ...over,
  };
}

function renderPage() {
  return renderWithQuery(
    <MemoryRouter>
      <ShoeDetail />
    </MemoryRouter>,
  );
}

describe("ShoeDetail page", () => {
  beforeEach(() => {
    routeId = "1";
    mockedGetShoe.mockResolvedValue(detail());
    mockedListActs.mockResolvedValue({ items: [], total: 0 });
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the header with name, brand/model, and shoe_type badge", async () => {
    renderPage();
    await screen.findByText("Vaporfly");
    expect(screen.getByText("Nike · ZoomX")).toBeInTheDocument();
    expect(screen.getByText("Race")).toBeInTheDocument();
  });

  it("renders the progress section and lifespan tile when a target is set", async () => {
    renderPage();
    await screen.findByText("Vaporfly");
    expect(screen.getByText("Lifespan target")).toBeInTheDocument();
    // 400000 m = 400 km
    expect(screen.getAllByText(/400 km/).length).toBeGreaterThan(0);
    expect(screen.getByTestId("shoe-progress")).toBeInTheDocument();
  });

  it("renders 'No target' when total_usable_distance_m is null", async () => {
    mockedGetShoe.mockResolvedValue(
      detail({ total_usable_distance_m: null, percent_used: null }),
    );
    renderPage();
    await screen.findByText("Vaporfly");
    expect(screen.getByText("No target")).toBeInTheDocument();
    expect(screen.getByTestId("shoe-progress-no-target")).toBeInTheDocument();
  });

  it("opens an edit modal prefilled with the shoe; submitting calls patchShoe", async () => {
    mockedPatchShoe.mockResolvedValue(detail({ name: "Vaporfly Renamed" }));
    renderPage();
    await screen.findByText("Vaporfly");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    const modal = screen.getByTestId("shoe-form-modal");
    expect(within(modal).getByDisplayValue("Vaporfly")).toBeInTheDocument();
    fireEvent.change(within(modal).getByDisplayValue("Vaporfly"), {
      target: { value: "Vaporfly Renamed" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(mockedPatchShoe).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ name: "Vaporfly Renamed" }),
      ),
    );
  });

  it("opens the retire confirm modal and calls retireShoe on confirm", async () => {
    mockedRetire.mockResolvedValue(detail({ status: "retired" }));
    renderPage();
    await screen.findByText("Vaporfly");
    fireEvent.click(screen.getByRole("button", { name: "Retire" }));
    expect(screen.getByTestId("retire-confirm-modal")).toBeInTheDocument();
    fireEvent.click(
      within(screen.getByTestId("retire-confirm-modal")).getByRole("button", {
        name: "Retire",
      }),
    );
    await waitFor(() => expect(mockedRetire).toHaveBeenCalledWith(1));
  });

  it("renders an Unretire button for a retired shoe and calls unretireShoe", async () => {
    mockedGetShoe.mockResolvedValue(
      detail({ status: "retired", retired_at: "2026-04-01T00:00:00Z" }),
    );
    mockedUnretire.mockResolvedValue(detail({ status: "active" }));
    renderPage();
    await screen.findByText("Vaporfly");
    fireEvent.click(screen.getByRole("button", { name: "Unretire" }));
    await waitFor(() => expect(mockedUnretire).toHaveBeenCalledWith(1));
  });

  it("renders the first page of tagged activities", async () => {
    mockedListActs.mockResolvedValue({
      items: [
        {
          id: 100,
          source: "strava",
          name: "Tempo run",
          sport_type: "Run",
          start_date: "2026-04-20T18:00:00Z",
          distance_m: 8000,
        },
      ],
      total: 1,
    });
    renderPage();
    await screen.findByText("Tempo run");
  });

  it("paginates: clicking Next calls listShoeActivities with offset=pageSize", async () => {
    const items = Array.from({ length: 20 }, (_, i) => ({
      id: i,
      source: "strava" as const,
      name: `Activity ${i}`,
      sport_type: "Run",
      start_date: "2026-04-20T18:00:00Z",
      distance_m: 5000,
    }));
    mockedListActs.mockResolvedValue({ items, total: 30 });
    renderPage();
    await screen.findByText("Activity 0");
    mockedListActs.mockResolvedValueOnce({
      items: items.slice(0, 10),
      total: 30,
    });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(mockedListActs).toHaveBeenLastCalledWith(1, {
        limit: 20,
        offset: 20,
      }),
    );
  });

  it("renders the 'no activities tagged yet' empty state when total is 0", async () => {
    renderPage();
    await screen.findByText(/No activities tagged yet/);
  });
});
