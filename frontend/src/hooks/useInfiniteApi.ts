import {
  useInfiniteQuery,
  type QueryKey,
} from "@tanstack/react-query";

export type UseInfiniteApiOptions = {
  staleTime?: number;
  gcTime?: number;
  enabled?: boolean;
};

/**
 * Cursor-paginated fetch keyed by `queryKey`. Thin wrapper over TanStack
 * `useInfiniteQuery` mirroring `useApi`'s retry / `refetchOnWindowFocus:false`
 * config and error extraction. `pageParam` is the opaque cursor string (or
 * `undefined` for the first page); `getNextPageParam` reads `has_more` /
 * `next_cursor` off the last loaded page.
 */
export function useInfiniteApi<
  TPage extends { next_cursor: string | null; has_more: boolean },
>(
  queryKey: QueryKey,
  queryFn: (cursor: string | undefined) => Promise<TPage>,
  options?: UseInfiniteApiOptions,
) {
  const { staleTime, gcTime, enabled = true } = options ?? {};

  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => queryFn(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) =>
      last.has_more ? (last.next_cursor ?? undefined) : undefined,
    staleTime,
    gcTime,
    enabled,
    refetchOnWindowFocus: false,
    // Cold starts / transient deploy errors: a bit more resilient than a single try.
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 8000),
  });

  // `isLoading` alone can be false for one frame before `fetchStatus` flips to
  // `fetching`, which made some UIs flash an empty state. Treat "enabled but
  // not yet fetched" (`pending` + `idle`) as loading. Disabled queries stay
  // idle per TanStack docs; do not mark those as loading here.
  const isLoading =
    query.isLoading ||
    (enabled && query.status === "pending" && query.fetchStatus === "idle");

  return {
    pages: (query.data?.pages ?? []) as TPage[],
    fetchNextPage: query.fetchNextPage,
    hasNextPage: query.hasNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading,
    error: query.error
      ? query.error instanceof Error
        ? query.error.message
        : String(query.error)
      : null,
  };
}
