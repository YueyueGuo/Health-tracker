import { ChevronLeft, ChevronRight, Calendar } from "lucide-react";

export function Header() {
  const today = new Date().toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  return (
    <header className="flex items-center justify-between py-2">
      <button
        type="button"
        className="p-2 text-slate-400 hover:text-white transition-colors"
        aria-label="Previous day"
      >
        <ChevronLeft size={24} />
      </button>

      <div className="flex items-center gap-2">
        <Calendar size={16} className="text-brand-green" />
        <h1 className="text-lg font-semibold text-white tracking-tight">
          {today}
        </h1>
      </div>

      <button
        type="button"
        className="p-2 text-slate-400 hover:text-white transition-colors"
        aria-label="Next day"
      >
        <ChevronRight size={24} />
      </button>
    </header>
  );
}
