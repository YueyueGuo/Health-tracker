import { useCallback } from "react";
import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

export type UseApiOptions = {
  staleTime?: number;
  gcTime?: number;
  enabled?: boolean;
};

/**
 * Cached data fetch keyed by `queryKey`. Uses TanStack Query so revisiting a
 * route shows cached data immediately while refreshing in the background
 * once data is stale.
 */
export function useApi<T>(
  queryKey: QueryKey,
  queryFn: () => Promise<T>,
  options?: UseApiOptions,
) {
  const queryClient = useQueryClient();
  const { staleTime, gcTime, enabled = true } = options ?? {};

  const query = useQuery({
    queryKey,
    queryFn,
    staleTime,
    gcTime,
    enabled,
    refetchOnWindowFocus: false,
    // Cold starts / transient deploy errors: a bit more resilient than a single try.
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 8000),
  });

  const setData = useCallback(
    (value: T) => {
      queryClient.setQueryData(queryKey, value);
    },
    [queryClient, queryKey],
  );

  const reload = useCallback(async () => {
    await query.refetch();
  }, [query]);

  // `isLoading` alone can be false for one frame before `fetchStatus` flips to
  // `fetching`, which made some UIs flash an empty state. Treat "enabled but
  // not yet fetched" (`pending` + `idle`) as loading. Disabled queries stay
  // idle per TanStack docs; do not mark those as loading here.
  const loading =
    query.isLoading ||
    (enabled &&
      query.status === "pending" &&
      query.fetchStatus === "idle");

  return {
    data: (query.data ?? null) as T | null,
    loading,
    error: query.error
      ? query.error instanceof Error
        ? query.error.message
        : String(query.error)
      : null,
    reload,
    setData,
    /** True once the query has completed at least one attempt (success or error). */
    isFetched: query.isFetched,
    isFetching: query.isFetching,
  };
}
