import type { QueryClient } from "@tanstack/react-query";

/** Default client cache for health streams (~daily freshness). */
export const APP_STALE_TIME_MS = 12 * 60 * 60 * 1000;

/** Keep unused query data through long backgrounding. */
export const APP_GC_TIME_MS = 24 * 60 * 60 * 1000;

/** Settings sync debug/status: always refetch when mounted. */
export const SYNC_DEBUG_STALE_TIME_MS = 0;

/** Profile data-sources card: connection status should feel current. */
export const SYNC_STATUS_CARD_STALE_TIME_MS = 5 * 60 * 1000;

const INVALIDATION_PREFIXES = [
  ["activities"],
  ["sleep"],
  ["recovery"],
  ["dashboard"],
  ["insights"],
  ["strength"],
  ["sync"],
] as const;

/** After a successful sync, refresh read models that depend on ingested data. */
export function invalidateAppDataQueries(queryClient: QueryClient): Promise<void> {
  return Promise.all(
    INVALIDATION_PREFIXES.map((key) =>
      queryClient.invalidateQueries({ queryKey: [...key] }),
    ),
  ).then(() => undefined);
}
