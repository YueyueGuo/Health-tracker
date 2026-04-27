import { FILTERS, type FilterId } from "../../lib/historyEvents";

interface Props {
  active: FilterId;
  onChange: (id: FilterId) => void;
}

export function HistoryFilters({ active, onChange }: Props) {
  return (
    <div className="flex overflow-x-auto gap-2 pb-1 scrollbar-hide">
      {FILTERS.map((filter) => {
        const isActive = active === filter.id;
        return (
          <button
            key={filter.id}
            type="button"
            onClick={() => onChange(filter.id)}
            className={`whitespace-nowrap px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
              isActive
                ? "bg-brand-green text-dashboard"
                : "bg-cardBorder/50 text-slate-400 hover:text-slate-200 hover:bg-cardBorder"
            }`}
          >
            {filter.label}
          </button>
        );
      })}
    </div>
  );
}
