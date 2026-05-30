import {
  FILTERS,
  TYPE_FILTERS,
  type FilterId,
  type TypeFilterId,
} from "../../lib/historyEvents";

interface Props {
  active: FilterId;
  onChange: (id: FilterId) => void;
  activeType: TypeFilterId;
  onTypeChange: (id: TypeFilterId) => void;
}

export function HistoryFilters({
  active,
  onChange,
  activeType,
  onTypeChange,
}: Props) {
  return (
    <div className="space-y-2">
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
      {active === "Run" && (
        <div className="flex overflow-x-auto gap-2 pb-1 scrollbar-hide">
          {TYPE_FILTERS.map((filter) => {
            const isActive = activeType === filter.id;
            return (
              <button
                key={filter.id}
                type="button"
                onClick={() => onTypeChange(filter.id)}
                className={`whitespace-nowrap px-3 py-1 rounded-full text-xs font-medium transition-colors ${
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
      )}
    </div>
  );
}
