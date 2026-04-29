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
    retry: 1,
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

  return {
    data: (query.data ?? null) as T | null,
    loading: query.isLoading,
    error: query.error
      ? query.error instanceof Error
        ? query.error.message
        : String(query.error)
      : null,
    reload,
    setData,
  };
}
