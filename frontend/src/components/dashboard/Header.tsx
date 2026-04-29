import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Calendar } from "lucide-react";
import { DayPicker } from "react-day-picker";
import "react-day-picker/style.css";
import { addDays, relativeDateLabel } from "../../utils/date";

interface HeaderProps {
  selectedDate: Date;
  onChange: (next: Date) => void;
  isToday: boolean;
}

export function Header({ selectedDate, onChange, isToday }: HeaderProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!pickerOpen) return;
    const onClick = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node)
      ) {
        setPickerOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPickerOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [pickerOpen]);

  const label = relativeDateLabel(selectedDate);
  const today = new Date();

  const goPrev = () => onChange(addDays(selectedDate, -1));
  const goNext = () => {
    if (isToday) return;
    onChange(addDays(selectedDate, 1));
  };

  return (
    <header className="relative flex items-center justify-between py-2">
      <button
        type="button"
        className="p-2 text-slate-400 hover:text-white transition-colors"
        aria-label="Previous day"
        onClick={goPrev}
      >
        <ChevronLeft size={24} />
      </button>

      <button
        type="button"
        className="flex items-center gap-2 px-2 py-1 rounded hover:bg-slate-800/40 transition-colors"
        aria-label="Open calendar"
        aria-expanded={pickerOpen}
        onClick={() => setPickerOpen((v) => !v)}
      >
        <Calendar size={16} className="text-brand-green" />
        <h1 className="text-lg font-semibold text-white tracking-tight">
          {label}
        </h1>
      </button>

      <button
        type="button"
        className="p-2 text-slate-400 hover:text-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-slate-400"
        aria-label="Next day"
        aria-disabled={isToday}
        disabled={isToday}
        onClick={goNext}
      >
        <ChevronRight size={24} />
      </button>

      {pickerOpen && (
        <div
          ref={popoverRef}
          className="absolute left-1/2 top-full z-30 mt-2 -translate-x-1/2 rounded-lg border border-cardBorder bg-dashboard shadow-xl"
          role="dialog"
        >
          <DayPicker
            mode="single"
            selected={selectedDate}
            onSelect={(d) => {
              if (!d) return;
              onChange(d);
              setPickerOpen(false);
            }}
            disabled={{ after: today }}
            showOutsideDays
            weekStartsOn={0}
          />
          <div className="flex justify-end p-2 border-t border-cardBorder">
            <button
              type="button"
              className="px-3 py-1 text-xs font-medium rounded text-slate-200 bg-cardBorder/60 hover:bg-cardBorder transition-colors"
              onClick={() => {
                onChange(new Date());
                setPickerOpen(false);
              }}
            >
              Today
            </button>
          </div>
        </div>
      )}
    </header>
  );
}
