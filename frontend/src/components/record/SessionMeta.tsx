import { formatRestTimer } from "./datetime";

interface Props {
  date: string;
  onDateChange: (date: string) => void;
  restSeconds: number | null;
}

export function SessionMeta({ date, onDateChange, restSeconds }: Props) {
  return (
    <div className="flex items-center justify-between gap-2 mb-2 px-1">
      <label className="flex items-center gap-2">
        <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">
          Date
        </span>
        <input
          type="date"
          value={date}
          onChange={(e) => onDateChange(e.target.value)}
          className="bg-cardBorder/30 border border-cardBorder rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-brand-green"
        />
      </label>
      <div className="flex items-center gap-2" aria-live="polite">
        <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">
          Rest
        </span>
        <span className="text-xs font-semibold text-slate-200 tabular-nums">
          {restSeconds != null ? formatRestTimer(restSeconds) : "—"}
        </span>
      </div>
    </div>
  );
}
