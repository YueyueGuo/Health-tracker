import { Clock } from "lucide-react";

interface Props {
  elapsed: number;
  isRunning: boolean;
  hasStarted: boolean;
  canFinish: boolean;
  onStart: () => void;
  onPause: () => void;
  onFinish: () => void;
  finishLabel: string;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

export function SessionHeader({
  elapsed,
  isRunning,
  hasStarted,
  canFinish,
  onStart,
  onPause,
  onFinish,
  finishLabel,
}: Props) {
  return (
    <div className="flex items-center justify-between mb-3 px-1">
      <div>
        <h1 className="text-xl font-bold text-white tracking-tight">Strength</h1>
        <div className="flex items-center gap-1.5 text-brand-green mt-0.5">
          <Clock size={14} />
          <span className="text-sm font-medium tabular-nums">
            {formatTime(elapsed)}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {!hasStarted ? (
          <button
            type="button"
            onClick={onStart}
            className="px-4 py-1.5 bg-brand-green text-dashboard font-semibold rounded-md text-sm hover:bg-emerald-500 transition-colors"
          >
            Start
          </button>
        ) : isRunning ? (
          <button
            type="button"
            onClick={onPause}
            className="px-3 py-1.5 bg-cardBorder text-white font-semibold rounded-md text-sm hover:bg-slate-700 transition-colors"
          >
            Pause
          </button>
        ) : (
          <button
            type="button"
            onClick={onStart}
            className="px-3 py-1.5 bg-cardBorder text-white font-semibold rounded-md text-sm hover:bg-slate-700 transition-colors"
          >
            Resume
          </button>
        )}
        <button
          type="button"
          onClick={onFinish}
          disabled={!canFinish}
          className={`px-4 py-1.5 font-semibold rounded-md text-sm transition-colors ${
            canFinish
              ? "bg-brand-green text-dashboard hover:bg-emerald-500"
              : "bg-cardBorder/50 text-slate-500 cursor-not-allowed"
          }`}
        >
          {finishLabel}
        </button>
      </div>
    </div>
  );
}
