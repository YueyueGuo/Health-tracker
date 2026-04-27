import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Filter } from "lucide-react";
import { useApi } from "../hooks/useApi";
import { fetchActivities } from "../api/activities";
import { fetchSleepSessions } from "../api/sleep";
import { fetchStrengthSessions } from "../api/strength";
import {
  applyHistoryFilter,
  buildHistoryEvents,
  type FilterId,
} from "../lib/historyEvents";
import { HistoryFilters } from "../components/history/HistoryFilters";
import { HistoryEventCard } from "../components/history/HistoryEventCard";

const containerVariants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.04 } },
};

export default function History() {
  const navigate = useNavigate();
  const [activeFilter, setActiveFilter] = useState<FilterId>("All");
  const [days, setDays] = useState(30);

  const activities = useApi(
    () => fetchActivities({ days, limit: 200 }),
    [days]
  );
  const sleep = useApi(() => fetchSleepSessions(days), [days]);
  const strength = useApi(() => fetchStrengthSessions(60), []);

  const loading = activities.loading || sleep.loading || strength.loading;
  const error = activities.error || sleep.error || strength.error;

  const allEvents = useMemo(
    () =>
      buildHistoryEvents(
        activities.data ?? [],
        sleep.data ?? [],
        strength.data ?? []
      ),
    [activities.data, sleep.data, strength.data]
  );
  const filtered = useMemo(
    () => applyHistoryFilter(allEvents, activeFilter),
    [allEvents, activeFilter]
  );

  return (
    <div className="pb-4 pt-4">
      <div className="sticky top-0 z-10 bg-dashboard/95 backdrop-blur-md pt-2 pb-3 -mx-4 px-4 sm:-mx-6 sm:px-6 mb-4">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-2xl font-bold text-white tracking-tight">
            History
          </h1>
          <div className="flex items-center gap-2">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              aria-label="Time range"
              className="bg-cardBorder/30 border border-cardBorder rounded-md px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-brand-green"
            >
              <option value={7}>7d</option>
              <option value={30}>30d</option>
              <option value={90}>90d</option>
              <option value={365}>1y</option>
            </select>
            <button
              type="button"
              aria-label="Filter"
              className="p-2 text-slate-400 hover:text-white transition-colors bg-cardBorder/30 rounded-full"
            >
              <Filter size={16} />
            </button>
          </div>
        </div>
        <HistoryFilters active={activeFilter} onChange={setActiveFilter} />
      </div>

      {loading && (
        <div className="text-center py-12 text-slate-500 text-sm">
          Loading history…
        </div>
      )}
      {!loading && error && (
        <div className="text-center py-12 text-brand-red text-sm">{error}</div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="text-center py-12 text-slate-500 text-sm">
          No events found for this filter.
        </div>
      )}

      {!loading && !error && filtered.length > 0 && (
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
    </div>
  );
}
