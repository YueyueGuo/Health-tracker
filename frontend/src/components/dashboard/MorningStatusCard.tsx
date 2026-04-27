import { Heart, Moon } from "lucide-react";
import { Card } from "../ui/Card";
import { CircularProgress } from "../ui/CircularProgress";
import { useApi } from "../../hooks/useApi";
import { fetchLatestSleep } from "../../api/sleep";
import { fetchRecovery } from "../../api/recovery";
import { useUnits, formatTemperature } from "../../hooks/useUnits";

const SOURCE_LABEL: Record<string, string> = {
  whoop: "WHOOP",
  eight_sleep: "Eight Sleep",
  oura: "Oura",
  garmin: "Garmin",
  manual: "Manual",
};

export function MorningStatusCard() {
  const { units } = useUnits();
  const sleep = useApi(fetchLatestSleep);
  const recovery = useApi(() => fetchRecovery(2));

  const latestSleep = sleep.data;
  const latestRecovery = recovery.data?.[0] ?? null;

  const recoveryScore = latestRecovery?.recovery_score ?? null;
  const sleepScore = latestSleep?.sleep_score ?? null;

  const total = latestSleep?.total_duration ?? null;
  const deep = latestSleep?.deep_sleep ?? null;
  const rem = latestSleep?.rem_sleep ?? null;
  const light = latestSleep?.light_sleep ?? null;
  const deepRemPct =
    total != null && total > 0 && (deep != null || rem != null)
      ? Math.round((((deep ?? 0) + (rem ?? 0)) / total) * 100)
      : null;

  const stagesTotal = (deep ?? 0) + (rem ?? 0) + (light ?? 0);
  const showStages = stagesTotal > 0;

  return (
    <Card className="p-4">
      <div className="flex justify-around items-center mb-6">
        <div className="flex flex-col items-center">
          <div className="flex items-center gap-1.5 mb-2">
            <Heart size={14} className="text-brand-green" />
            <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
              Recovery
            </span>
          </div>
          <CircularProgress
            value={recoveryScore ?? 0}
            size={100}
            strokeWidth={8}
            colorClass="text-brand-green"
          >
            <div className="flex flex-col items-center">
              <span className="text-2xl font-bold text-white">
                {recoveryScore != null ? `${Math.round(recoveryScore)}%` : "—"}
              </span>
            </div>
          </CircularProgress>
          <span className="text-[10px] text-slate-500 mt-2 bg-slate-800/50 px-2 py-0.5 rounded">
            {sourceLabel(latestRecovery?.source) ?? "Recovery"}
          </span>
        </div>

        <div className="w-px h-24 bg-cardBorder"></div>

        <div className="flex flex-col items-center">
          <div className="flex items-center gap-1.5 mb-2">
            <Moon size={14} className="text-sky-400" />
            <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
              Sleep
            </span>
          </div>
          <CircularProgress
            value={sleepScore ?? 0}
            size={100}
            strokeWidth={8}
            colorClass="text-sky-400"
          >
            <div className="flex flex-col items-center">
              <span className="text-2xl font-bold text-white">
                {sleepScore != null ? Math.round(sleepScore) : "—"}
              </span>
            </div>
          </CircularProgress>
          <span className="text-[10px] text-slate-500 mt-2 bg-slate-800/50 px-2 py-0.5 rounded">
            {sourceLabel(latestSleep?.source) ?? "Sleep"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 pt-4 border-t border-cardBorder">
        <Metric
          label="HRV"
          value={latestSleep?.hrv != null ? Math.round(latestSleep.hrv) : null}
          unit="ms"
        />
        <Metric
          label="RHR"
          value={
            latestRecovery?.resting_hr != null
              ? Math.round(latestRecovery.resting_hr)
              : latestSleep?.avg_hr != null
                ? Math.round(latestSleep.avg_hr)
                : null
          }
          unit="bpm"
        />
        <Metric
          label="Sleep Time"
          value={total != null ? formatDuration(total) : null}
        />
        <Metric
          label="Deep/REM"
          value={deepRemPct != null ? `${deepRemPct}%` : null}
        />
      </div>

      {(showStages ||
        latestSleep?.respiratory_rate != null ||
        latestSleep?.bed_temp != null) && (
        <div className="grid grid-cols-4 gap-3 pt-3 mt-3 border-t border-cardBorder/50">
          {showStages ? (
            <div className="flex flex-col col-span-2">
              <span className="text-[10px] text-slate-500 mb-1">
                Sleep Stages
              </span>
              <div className="h-1.5 w-full flex rounded-full overflow-hidden gap-0.5">
                <div
                  className="bg-sky-900 h-full"
                  style={{
                    width: `${((deep ?? 0) / stagesTotal) * 100}%`,
                  }}
                />
                <div
                  className="bg-sky-600 h-full"
                  style={{
                    width: `${((rem ?? 0) / stagesTotal) * 100}%`,
                  }}
                />
                <div
                  className="bg-sky-300 h-full"
                  style={{
                    width: `${((light ?? 0) / stagesTotal) * 100}%`,
                  }}
                />
              </div>
            </div>
          ) : (
            <div className="col-span-2" />
          )}
          <div className="flex flex-col">
            <span className="text-[10px] text-slate-500 mb-0.5">Resp Rate</span>
            <span className="text-xs font-medium text-slate-300">
              {latestSleep?.respiratory_rate != null
                ? `${latestSleep.respiratory_rate.toFixed(1)} rpm`
                : "—"}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] text-slate-500 mb-0.5">Skin Temp</span>
            <span className="text-xs font-medium text-brand-amber">
              {latestSleep?.bed_temp != null
                ? formatTemperature(latestSleep.bed_temp, units)
                : "—"}
            </span>
          </div>
        </div>
      )}
    </Card>
  );
}

function Metric({
  label,
  value,
  unit,
}: {
  label: string;
  value: string | number | null;
  unit?: string;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] text-slate-500 mb-0.5">{label}</span>
      <span className="text-sm font-semibold text-slate-200">
        {value ?? "—"}
        {value != null && unit && (
          <span className="text-[10px] text-slate-500 font-normal ml-1">
            {unit}
          </span>
        )}
      </span>
    </div>
  );
}

function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}h ${m}m`;
}

function sourceLabel(source: string | null | undefined): string | null {
  if (!source) return null;
  return SOURCE_LABEL[source.toLowerCase()] ?? source;
}
