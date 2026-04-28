import { useNavigate } from "react-router-dom";
import {
  Activity,
  Battery,
  BedDouble,
  ChevronLeft,
  Heart,
  Moon,
  Thermometer,
  Timer,
  Wind,
} from "lucide-react";
import type { SleepSession } from "../../api/sleep";
import type { RecoveryRecord } from "../../api/recovery";
import { Card } from "../ui/Card";
import { CircularProgress } from "../ui/CircularProgress";
import { formatTemperature, useUnits } from "../../hooks/useUnits";

const SOURCE_LABEL: Record<string, string> = {
  whoop: "WHOOP",
  eight_sleep: "Eight Sleep",
  oura: "Oura",
  garmin: "Garmin",
  manual: "Manual",
};

type DiffTone = "positive" | "negative" | "neutral";

export interface SleepRecoveryDetailsCardProps {
  sleep: SleepSession | null;
  recovery: RecoveryRecord | null;
}

export function SleepRecoveryDetailsCard({
  sleep,
  recovery,
}: SleepRecoveryDetailsCardProps) {
  const navigate = useNavigate();
  const { units } = useUnits();

  const recoveryLabel = sourceLabel(recovery?.source) ?? "WHOOP";
  const sleepLabel = sourceLabel(sleep?.source) ?? "Eight Sleep";
  const headerDate = formatHeaderDate(sleep?.date ?? recovery?.date ?? null);

  const recoveryScore = recovery?.recovery_score ?? null;
  const sleepScore = sleep?.sleep_score ?? null;

  const whoopHrv = recovery?.hrv ?? null;
  const eightHrv = sleep?.hrv ?? null;
  const whoopRhr = recovery?.resting_hr ?? null;
  const eightRhr = sleep?.avg_hr ?? null;
  const whoopTotalSleepMin: number | null = null;
  const eightTotalSleepMin = sleep?.total_duration ?? null;
  const whoopResp = null as number | null;
  const eightResp = sleep?.respiratory_rate ?? null;

  const comparisons: {
    label: string;
    icon: typeof Timer;
    whoopDisplay: string;
    eightDisplay: string;
    whoopNum: number | null;
    eightNum: number | null;
    lowerIsBetter: boolean;
  }[] = [
    {
      label: "Total Sleep",
      icon: Timer,
      whoopDisplay: formatDurationMinutes(whoopTotalSleepMin),
      eightDisplay: formatDurationMinutes(eightTotalSleepMin),
      whoopNum: whoopTotalSleepMin,
      eightNum: eightTotalSleepMin,
      lowerIsBetter: false,
    },
    {
      label: "HRV",
      icon: Activity,
      whoopDisplay: whoopHrv != null ? `${Math.round(whoopHrv)} ms` : "—",
      eightDisplay: eightHrv != null ? `${Math.round(eightHrv)} ms` : "—",
      whoopNum: whoopHrv,
      eightNum: eightHrv,
      lowerIsBetter: false,
    },
    {
      label: "Resting HR",
      icon: Heart,
      whoopDisplay: whoopRhr != null ? `${Math.round(whoopRhr)} bpm` : "—",
      eightDisplay: eightRhr != null ? `${Math.round(eightRhr)} bpm` : "—",
      whoopNum: whoopRhr,
      eightNum: eightRhr,
      lowerIsBetter: true,
    },
    {
      label: "Resp. Rate",
      icon: Wind,
      whoopDisplay: whoopResp != null ? `${whoopResp.toFixed(1)} rpm` : "—",
      eightDisplay: eightResp != null ? `${eightResp.toFixed(1)} rpm` : "—",
      whoopNum: whoopResp,
      eightNum: eightResp,
      lowerIsBetter: true,
    },
  ];

  const stages = computeStagePercents(sleep);
  const hasEightStages = stages != null && stages.total > 0;

  return (
    <div className="pb-2 pt-2">
      <div className="px-1 mb-3 sticky top-0 z-20 bg-dashboard/95 backdrop-blur-md pt-1 pb-3 -mx-4 px-4 sm:mx-0 sm:px-0">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="p-1.5 -ml-1.5 text-slate-400 hover:text-white transition-colors bg-cardBorder/30 rounded-full"
            aria-label="Go back"
          >
            <ChevronLeft size={18} />
          </button>
          <div>
            <h1 className="text-lg font-bold text-white tracking-tight">
              Sleep & Recovery
            </h1>
            <p className="text-[10px] text-slate-400">{headerDate}</p>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Card className="p-4 flex flex-col items-center justify-center">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-3">
              {recoveryLabel} Recovery
            </div>
            <CircularProgress
              value={recoveryScore ?? 0}
              size={80}
              strokeWidth={6}
              colorClass="text-brand-green"
            >
              <span className="text-xl font-bold text-white">
                {recoveryScore != null ? `${Math.round(recoveryScore)}%` : "—"}
              </span>
            </CircularProgress>
          </Card>

          <Card className="p-4 flex flex-col items-center justify-center">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-3">
              {sleepLabel} Sleep
            </div>
            <CircularProgress
              value={sleepScore ?? 0}
              size={80}
              strokeWidth={6}
              colorClass="text-sky-400"
            >
              <span className="text-xl font-bold text-white">
                {sleepScore != null ? Math.round(sleepScore) : "—"}
              </span>
            </CircularProgress>
          </Card>
        </div>

        <Card className="p-0 overflow-hidden">
          <div className="grid grid-cols-[1.2fr_1fr_1fr_0.8fr] gap-2 p-3 border-b border-cardBorder/50 bg-cardBorder/10">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
              Metric
            </div>
            <div className="text-[10px] font-bold text-slate-300 uppercase tracking-wider text-right">
              {recoveryLabel}
            </div>
            <div className="text-[10px] font-bold text-sky-400 uppercase tracking-wider text-right">
              {sleepLabel}
            </div>
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider text-right">
              Δ Diff
            </div>
          </div>

          <div className="p-2 space-y-1">
            {comparisons.map((comp, idx) => {
              const Icon = comp.icon;
              const { text, tone } = diffDisplay(
                comp.whoopNum,
                comp.eightNum,
                comp.lowerIsBetter
              );
              return (
                <div
                  key={idx}
                  className="grid grid-cols-[1.2fr_1fr_1fr_0.8fr] gap-2 p-2 items-center rounded hover:bg-cardBorder/20 transition-colors"
                >
                  <div className="flex items-center gap-2 text-slate-300">
                    <Icon size={14} className="text-slate-500" />
                    <span className="text-xs font-medium">{comp.label}</span>
                  </div>
                  <div className="text-xs font-bold text-white text-right">
                    {comp.whoopDisplay}
                  </div>
                  <div className="text-xs font-bold text-white text-right">
                    {comp.eightDisplay}
                  </div>
                  <div
                    className={`text-[11px] font-bold text-right ${
                      tone === "positive"
                        ? "text-brand-green"
                        : tone === "negative"
                          ? "text-brand-red"
                          : "text-slate-400"
                    }`}
                  >
                    {text}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        <Card className="p-4">
          <div className="flex items-center gap-2 mb-4">
            <Moon size={14} className="text-slate-400" />
            <h3 className="text-sm font-semibold text-slate-200">Sleep Stages</h3>
          </div>

          <div className="space-y-4 mb-5">
            <div>
              <div className="flex justify-between text-[10px] font-bold text-slate-300 mb-1.5">
                <span>{recoveryLabel}</span>
              </div>
              <div className="h-4 w-full rounded-full overflow-hidden bg-slate-800/60 border border-cardBorder/30" />
              <p className="text-[10px] text-slate-500 mt-1">No stage breakdown for this source.</p>
            </div>

            <div>
              <div className="flex justify-between text-[10px] font-bold text-sky-400 mb-1.5">
                <span>{sleepLabel}</span>
              </div>
              {hasEightStages && stages ? (
                <div className="h-4 w-full flex rounded-full overflow-hidden gap-0.5">
                  <div
                    className="bg-slate-700 h-full min-w-[2px]"
                    style={{ width: `${stages.pct.awake}%` }}
                  />
                  <div
                    className="bg-blue-800 h-full min-w-[2px]"
                    style={{ width: `${stages.pct.light}%` }}
                  />
                  <div
                    className="bg-blue-600 h-full min-w-[2px]"
                    style={{ width: `${stages.pct.rem}%` }}
                  />
                  <div
                    className="bg-blue-400 h-full min-w-[2px]"
                    style={{ width: `${stages.pct.deep}%` }}
                  />
                </div>
              ) : (
                <div className="h-4 w-full rounded-full bg-slate-800/60 border border-cardBorder/30" />
              )}
            </div>
          </div>

          <div className="border-t border-cardBorder/50 pt-3">
            <div className="grid grid-cols-[1fr_1fr_1fr] gap-2 mb-2 px-1">
              <div className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">
                Stage
              </div>
              <div className="text-[9px] font-bold text-slate-300 uppercase tracking-wider text-right">
                {recoveryLabel}
              </div>
              <div className="text-[9px] font-bold text-sky-400 uppercase tracking-wider text-right">
                {sleepLabel}
              </div>
            </div>

            <div className="space-y-2">
              {(
                [
                  { key: "awake" as const, label: "Awake", dot: "bg-slate-700" },
                  { key: "light" as const, label: "Light", dot: "bg-blue-800" },
                  { key: "rem" as const, label: "REM", dot: "bg-blue-600" },
                  { key: "deep" as const, label: "Deep", dot: "bg-blue-400" },
                ] as const
              ).map((row) => (
                <div
                  key={row.key}
                  className="grid grid-cols-[1fr_1fr_1fr] gap-2 px-1 items-center"
                >
                  <div className="flex items-center gap-1.5">
                    <div className={`w-2 h-2 rounded-sm ${row.dot}`} />
                    <span className="text-xs text-slate-400">{row.label}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-xs text-slate-500">—</span>
                  </div>
                  <div className="text-right">
                    {hasEightStages && stages ? (
                      <>
                        <span className="text-xs font-bold text-white">
                          {formatStageCell(stages.minutes[row.key])}
                        </span>
                        <span className="text-[10px] text-slate-500 ml-1">
                          ({stages.pct[row.key]}%)
                        </span>
                      </>
                    ) : (
                      <span className="text-xs text-slate-500">—</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <div className="grid grid-cols-2 gap-3">
          <Card className="p-3 border-slate-500/20">
            <div className="text-[10px] font-bold text-slate-300 uppercase tracking-wider mb-3">
              {recoveryLabel} Insights
            </div>
            <div className="space-y-3">
              {recovery?.strain_score != null && (
                <div>
                  <div className="flex items-center gap-1.5 text-slate-400 mb-0.5">
                    <Battery size={12} />
                    <span className="text-[9px] uppercase tracking-wider font-medium">
                      Strain
                    </span>
                  </div>
                  <div className="text-sm font-bold text-white">
                    {recovery.strain_score.toFixed(1)}
                  </div>
                </div>
              )}
              {recovery?.skin_temp != null && (
                <div>
                  <div className="flex items-center gap-1.5 text-slate-400 mb-0.5">
                    <Thermometer size={12} />
                    <span className="text-[9px] uppercase tracking-wider font-medium">
                      Skin temp
                    </span>
                  </div>
                  <div className="text-sm font-bold text-brand-amber">
                    {formatTemperature(recovery.skin_temp, units)}
                  </div>
                </div>
              )}
              {recovery?.spo2 != null && (
                <div>
                  <div className="flex items-center gap-1.5 text-slate-400 mb-0.5">
                    <Activity size={12} />
                    <span className="text-[9px] uppercase tracking-wider font-medium">
                      SpO₂
                    </span>
                  </div>
                  <div className="text-sm font-bold text-white">
                    {recovery.spo2.toFixed(1)}%
                  </div>
                </div>
              )}
              {recovery?.strain_score == null &&
                recovery?.skin_temp == null &&
                recovery?.spo2 == null && (
                  <p className="text-[10px] text-slate-500">No extra recovery metrics.</p>
                )}
            </div>
          </Card>

          <Card className="p-3 border-sky-400/20">
            <div className="text-[10px] font-bold text-sky-400 uppercase tracking-wider mb-3">
              {sleepLabel} Insights
            </div>
            <div className="space-y-3">
              <div>
                <div className="flex items-center gap-1.5 text-slate-400 mb-0.5">
                  <BedDouble size={12} />
                  <span className="text-[9px] uppercase tracking-wider font-medium">
                    Latency
                  </span>
                </div>
                <div className="text-sm font-bold text-white">
                  {formatLatency(sleep?.latency)}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="flex items-center gap-1.5 text-slate-400 mb-0.5">
                    <Timer size={12} />
                    <span className="text-[9px] uppercase tracking-wider font-medium">
                      WASO
                    </span>
                  </div>
                  <div className="text-sm font-bold text-white">
                    {sleep?.waso_duration != null
                      ? `${Math.round(sleep.waso_duration)}m`
                      : "—"}
                  </div>
                </div>
                <div>
                  <div className="flex items-center gap-1.5 text-slate-400 mb-0.5">
                    <Moon size={12} />
                    <span className="text-[9px] uppercase tracking-wider font-medium">
                      Wakes
                    </span>
                  </div>
                  <div className="text-sm font-bold text-white">
                    {sleep?.wake_count != null ? String(sleep.wake_count) : "—"}
                  </div>
                </div>
              </div>
              <div>
                <div className="flex items-center gap-1.5 text-slate-400 mb-0.5">
                  <Thermometer size={12} />
                  <span className="text-[9px] uppercase tracking-wider font-medium">
                    Bed temp
                  </span>
                </div>
                <div className="text-sm font-bold text-white">
                  {sleep?.bed_temp != null
                    ? formatTemperature(sleep.bed_temp, units)
                    : "—"}
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function sourceLabel(source: string | null | undefined): string | null {
  if (!source) return null;
  return SOURCE_LABEL[source.toLowerCase()] ?? source;
}

function formatHeaderDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.includes("T") ? iso : `${iso}T12:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function formatDurationMinutes(minutes?: number | null): string {
  if (minutes == null) return "—";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatLatency(latencySec?: number | null): string {
  if (latencySec == null) return "—";
  const m = Math.round(latencySec / 60);
  return `${m}m`;
}

function formatStageCell(minutes: number): string {
  if (!minutes || minutes <= 0) return "0m";
  if (minutes >= 60) {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes % 60);
    return m > 0 ? `${h}h ${m}m` : `${h}h`;
  }
  return `${Math.round(minutes)}m`;
}

function computeStagePercents(session: SleepSession | null): {
  total: number;
  minutes: { awake: number; light: number; rem: number; deep: number };
  pct: { awake: number; light: number; rem: number; deep: number };
} | null {
  if (!session) return null;
  const awake = session.awake_time ?? 0;
  const light = session.light_sleep ?? 0;
  const rem = session.rem_sleep ?? 0;
  const deep = session.deep_sleep ?? 0;
  const total = awake + light + rem + deep;
  if (total <= 0) return null;
  const keys = ["awake", "light", "rem", "deep"] as const;
  const mins = { awake, light, rem, deep };
  const exact = keys.map((k) => (mins[k] / total) * 100);
  const floors = exact.map((x) => Math.floor(x));
  let remainder = 100 - floors.reduce((a, b) => a + b, 0);
  const fracs = exact.map((x, i) => ({ i, f: x - Math.floor(x) }));
  fracs.sort((a, b) => b.f - a.f);
  for (let j = 0; j < fracs.length && remainder > 0; j++) {
    floors[fracs[j].i]++;
    remainder--;
  }
  const pct = {
    awake: floors[0],
    light: floors[1],
    rem: floors[2],
    deep: floors[3],
  };
  return { total, minutes: { awake, light, rem, deep }, pct };
}

function diffDisplay(
  whoop: number | null,
  eight: number | null,
  lowerIsBetter: boolean
): { text: string; tone: DiffTone } {
  if (whoop == null || eight == null || whoop === 0) {
    return { text: "—", tone: "neutral" };
  }
  const raw = ((eight - whoop) / whoop) * 100;
  const rounded = Math.round(raw);
  const sign = rounded > 0 ? "+" : "";
  const text = `${sign}${rounded}%`;
  if (Math.abs(rounded) < 1) return { text, tone: "neutral" };
  const good = lowerIsBetter ? raw < 0 : raw > 0;
  const bad = lowerIsBetter ? raw > 0 : raw < 0;
  const tone: DiffTone = good ? "positive" : bad ? "negative" : "neutral";
  return { text, tone };
}
