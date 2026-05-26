/**
 * React Query hooks for the running-shoe surfaces.
 *
 * `useShoesList(filter)`     — list view (`/shoes` page, settings card).
 * `useShoeDetail(id)`        — detail view.
 * `useShoeActivities(id, p)` — paginated tagged activities on detail.
 * `invalidateShoes`          — single helper called after any mutation
 *                              (create/edit/retire/unretire/tag) so the
 *                              activity-detail page and any open list
 *                              both refetch.
 */
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useApi } from "./useApi";
import {
  getShoe,
  listShoeActivities,
  listShoes,
  type ShoeListFilter,
} from "../api/shoes";

export function useShoesList(filter: ShoeListFilter) {
  return useApi(["shoes", "list", filter], () => listShoes(filter));
}

export function useShoeDetail(id: number | null) {
  return useApi(
    ["shoes", "detail", id],
    () => {
      if (id == null) {
        // Defensive: `enabled` already gates this, but TS wants a path.
        return Promise.reject(new Error("shoe id is required"));
      }
      return getShoe(id);
    },
    { enabled: id != null },
  );
}

export function useShoeActivities(
  id: number | null,
  page: { limit: number; offset: number },
) {
  return useApi(
    ["shoes", "activities", id, page.limit, page.offset],
    () => {
      if (id == null) {
        return Promise.reject(new Error("shoe id is required"));
      }
      return listShoeActivities(id, { limit: page.limit, offset: page.offset });
    },
    { enabled: id != null },
  );
}

/**
 * Invalidate every cache touched by a shoe mutation. Touches both the
 * shoe queries (the list, the detail, the tagged-activities sub-list)
 * and the activity-detail cache, because tagging a shoe on a run flips
 * `activity.shoe_id` and the parent page needs to repaint.
 */
export function invalidateShoes(client: QueryClient) {
  return Promise.all([
    client.invalidateQueries({ queryKey: ["shoes"] }),
    client.invalidateQueries({ queryKey: ["activities"] }),
  ]);
}

/** Hook flavor for components that already have the QueryClient in scope. */
export function useInvalidateShoes() {
  const client = useQueryClient();
  return () => invalidateShoes(client);
}
