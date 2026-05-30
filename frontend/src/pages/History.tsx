import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Filter } from "lucide-react";
import { useInfiniteApi } from "../hooks/useInfiniteApi";
import { fetchHistoryFeed } from "../api/dashboard";
import {
  applyHistoryFilter,
  applyTypeFilter,
  buildHistoryEvents,
  type FilterId,
  type TypeFilterId,
} from "../lib/historyEvents";
import { HistoryFilters } from "../components/history/HistoryFilters";
import { HistoryEventCard } from "../components/history/HistoryEventCard";

const containerVariants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.04 } },
};

// Below this many filtered rows, eagerly fetch the next page so an active
// client-side filter (which only sees rows loaded so far) doesn't strand the
// user on a near-empty view that actually has older matches further back.
const FILTER_AUTOLOAD_THRESHOLD = 5;

export default function History() {
  const navigate = useNavigate();
  const [activeFilter, setActiveFilter] = useState<FilterId>("All");
  const [activeType, setActiveType] = useState<TypeFilterId>("AllTypes");

  const {
    pages,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    error,
  } = useInfiniteApi(["dashboard", "history-feed"], (cursor) =>
    fetchHistoryFeed(cursor),
  );

  // Concatenate every loaded page's three source arrays, then shape + sort +
  // cross-source dedup ONCE via the shared builder (newest-first).
  const allEvents = useMemo(() => {
    const activities = pages.flatMap((p) => p.activities);
    const sleep = pages.flatMap((p) => p.sleep);
    const strength = pages.flatMap((p) => p.strength);
    const events = buildHistoryEvents(activities, sleep, strength);
    // Guard against any page-boundary overlap: ids are source-namespaced
    // (e.g. `strava-123`, `sleep-5`, `strength-2026-05-30`), so dedupe by id.
    const seen = new Set<string>();
    return events.filter((e) => {
      if (seen.has(e.id)) return false;
      seen.add(e.id);
      return true;
    });
  }, [pages]);

  // The run-type filter only applies to runs, so it's composed in only when
  // the "Runs" sport filter is active (and its row is the only one shown).
  const filtered = useMemo(() => {
    const bySport = applyHistoryFilter(allEvents, activeFilter);
    return activeFilter === "Run"
      ? applyTypeFilter(bySport, activeType)
      : bySport;
  }, [allEvents, activeFilter, activeType]);

  const filterActive = activeFilter !== "All" || activeType !== "AllTypes";

  // Filter-vs-pagination UX: with a filter active, a short filtered list that
  // still has older pages should keep loading so matches aren't hidden behind
  // the cursor. Guard against loops by only firing when not already fetching.
  useEffect(() => {
    if (
      filterActive &&
      filtered.length < FILTER_AUTOLOAD_THRESHOLD &&
      hasNextPage &&
      !isFetchingNextPage
    ) {
      fetchNextPage();
    }
  }, [
    filterActive,
    filtered.length,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  ]);

  // IntersectionObserver sentinel: load the next page when it scrolls into view.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node) return;
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      const entry = entries[0];
      if (entry?.isIntersecting && hasNextPage && !isFetchingNextPage) {
        fetchNextPage();
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Reset the run-type sub-filter whenever we leave the Runs view so a stale
  // selection can't silently hide rows once the type row is hidden again.
  const handleFilterChange = (id: FilterId) => {
    setActiveFilter(id);
    if (id !== "Run") setActiveType("AllTypes");
  };

  return (
    <div className="pb-4 pt-4">
      <div className="sticky top-0 z-10 bg-dashboard/95 backdrop-blur-md pt-2 pb-3 -mx-4 px-4 sm:-mx-6 sm:px-6 mb-4">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-2xl font-bold text-white tracking-tight">
            History
          </h1>
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Filter"
              className="p-2 text-slate-400 hover:text-white transition-colors bg-cardBorder/30 rounded-full"
            >
              <Filter size={16} />
            </button>
          </div>
        </div>
        <HistoryFilters
          active={activeFilter}
          onChange={handleFilterChange}
          activeType={activeType}
          onTypeChange={setActiveType}
        />
      </div>

      {isLoading && (
        <div className="text-center py-12 text-slate-500 text-sm">
          Loading history…
        </div>
      )}
      {!isLoading && error && (
        <div className="text-center py-12 text-brand-red text-sm">{error}</div>
      )}

      {!isLoading && !error && filtered.length === 0 && (
        <div className="text-center py-12 text-slate-500 text-sm">
          No events found for this filter.
        </div>
      )}

      {!isLoading && !error && filtered.length > 0 && (
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="show"
          className="space-y-3"
        >
          {filtered.map((event) => (
            <HistoryEventCard
              key={event.id}
              event={event}
              onClick={
                event.navigateTo ? () => navigate(event.navigateTo!) : undefined
              }
            />
          ))}
        </motion.div>
      )}

      {!isLoading && !error && (
        <>
          {/* Sentinel watched by IntersectionObserver to trigger the next page. */}
          <div ref={sentinelRef} aria-hidden="true" className="h-px" />
          {isFetchingNextPage && (
            <div className="text-center py-6 text-slate-500 text-sm">
              Loading more…
            </div>
          )}
          {!hasNextPage && !isFetchingNextPage && filtered.length > 0 && (
            <div className="text-center py-6 text-slate-600 text-xs">
              You’re all caught up
            </div>
          )}
        </>
      )}
    </div>
  );
}
