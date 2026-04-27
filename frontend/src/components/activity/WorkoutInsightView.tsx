import { Card } from "../ui/Card";
import type { WorkoutInsight } from "../../api/insights";

interface Props {
  insight: WorkoutInsight | null;
  model: string | null;
  error: string | null;
  analyzing: boolean;
  onAnalyze: () => void;
}

export default function WorkoutInsightView({
  insight,
  model,
  error,
  analyzing,
  onAnalyze,
}: Props) {
  return (
    <Card className="!p-4">
      <h3 className="text-sm font-semibold text-slate-200 mb-3">AI Analysis</h3>
      {!insight && !error && (
        <button
          type="button"
          onClick={onAnalyze}
          disabled={analyzing}
          className="px-3 py-1.5 rounded-md text-xs font-medium bg-cardBorder text-slate-200 hover:bg-cardBorder/70 transition-colors disabled:opacity-50"
        >
          {analyzing ? "Analyzing…" : "Analyze This Workout"}
        </button>
      )}
      {error && <div className="text-xs text-brand-red">{error}</div>}
      {insight && (
        <div className="text-sm text-slate-300 leading-relaxed">
          <h4 className="text-base font-semibold text-white mt-0 mb-1">
            {insight.headline}
          </h4>
          <p className="mt-0 mb-3">{insight.takeaway}</p>
          {insight.notable_segments.length > 0 && (
            <div className="mb-3">
              <h5 className="text-[11px] uppercase tracking-wider text-slate-500 font-medium mb-1">
                Notable segments
              </h5>
              <ul className="m-0 pl-4 space-y-1">
                {insight.notable_segments.map((s, i) => (
                  <li key={i}>
                    <span className="font-semibold text-white">
                      {s.label}:
                    </span>{" "}
                    {s.detail}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {insight.vs_history && (
            <div className="mb-3">
              <h5 className="text-[11px] uppercase tracking-wider text-slate-500 font-medium mb-1">
                vs. history
              </h5>
              <p className="m-0">{insight.vs_history}</p>
            </div>
          )}
          {insight.flags.length > 0 && (
            <div className="flex gap-1.5 flex-wrap mt-2">
              {insight.flags.map((f) => (
                <span
                  key={f}
                  className="px-2 py-0.5 rounded text-[10px] bg-cardBorder/50 text-slate-300"
                >
                  {f}
                </span>
              ))}
            </div>
          )}
          {model && (
            <div className="text-[10px] text-slate-500 mt-3">Model: {model}</div>
          )}
        </div>
      )}
    </Card>
  );
}
