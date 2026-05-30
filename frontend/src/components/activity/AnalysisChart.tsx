import { useMemo, useState } from "react";
import {
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card } from "../ui/Card";
import { useUnits } from "../../hooks/useUnits";
import type { ActivitySource } from "../../api/activities";
import {
  formatPaceTick,
  niceTickRange,
  paceDecimal,
  paceUnitLabel,
  speedUnitLabel,
  speedValue,
} from "./utils";

type AnalysisMode = "run" | "ride" | "strength";

interface Props {
  mode: AnalysisMode;
  streams: Record<string, number[]> | null;
  streamsLoading: boolean;
  streamsError: string | null;
  onLoadStreams: () => void;
  streamsCached: boolean;
  /** Source of the underlying workout. Apple Health streams are
   *  reconstructed server-side from the cached `raw_payload`, so the
   *  lazy "Load Streams" button is hidden and the copy reflects that. */
  source?: ActivitySource | null;
}

interface ChartDatum {
  time: number;
  hr?: number;
  secondary?: number;
}

export default function AnalysisChart({
  mode,
  streams,
  streamsLoading,
  streamsError,
  onLoadStreams,
  streamsCached,
  source,
}: Props) {
  const { units } = useUnits();
  const isApple = source === "apple_health";
  const [showHR, setShowHR] = useState(true);
  const [showSecondary, setShowSecondary] = useState(mode !== "strength");

  const chartData = useMemo<ChartDatum[]>(() => {
    if (!streams) return [];
    const time = streams.time || [];
    const hr = streams.heartrate;
    const velocity = streams.velocity_smooth;
    const watts = streams.watts;
    return time.map((t, i) => {
      const datum: ChartDatum = { time: Math.round(t / 60) };
      if (hr && hr[i] != null) datum.hr = hr[i];
      if (mode === "ride" && watts && watts[i] != null) {
        datum.secondary = watts[i];
      } else if (
        mode === "run" &&
        velocity &&
        velocity[i] != null &&
        velocity[i] > 0
      ) {
        datum.secondary = paceDecimal(velocity[i], units);
      } else if (
        mode === "ride" &&
        (!watts || watts.length === 0) &&
        velocity &&
        velocity[i] != null
      ) {
        // Fallback: rides without power streams render speed instead.
        datum.secondary = speedValue(velocity[i], units);
      }
      return datum;
    });
  }, [streams, mode, units]);

  const hasHR = chartData.some((d) => d.hr != null);
  const hasSecondary = chartData.some((d) => d.secondary != null);
  const ridePowerAvailable =
    mode === "ride" && (streams?.watts?.length ?? 0) > 0;
  // Apple rides never carry power; hide the Power toggle entirely so the
  // chart controls stay honest. Strava rides without watts still expose
  // the toggle as a "Speed" fallback.
  const ridePowerToggleHidden = mode === "ride" && isApple && !ridePowerAvailable;
  const secondaryName =
    mode === "run"
      ? "Pace"
      : mode === "ride"
        ? ridePowerAvailable
          ? "Power"
          : "Speed"
        : null;

  const secondaryUnit =
    mode === "run"
      ? paceUnitLabel(units)
      : mode === "ride"
        ? ridePowerAvailable
          ? "W"
          : speedUnitLabel(units)
        : "";

  const reverseSecondary = mode === "run";

  // --- Computed axis domains and tick arrays ---------------------------------

  /** X-axis (time in minutes): evenly-spaced ticks based on total duration. */
  const xTicks = useMemo(() => {
    if (chartData.length === 0) return undefined;
    const maxTime = chartData[chartData.length - 1].time;
    let interval: number;
    if (maxTime <= 20) interval = 2;
    else if (maxTime <= 40) interval = 5;
    else if (maxTime <= 90) interval = 10;
    else interval = 15;
    return niceTickRange(0, maxTime, interval);
  }, [chartData]);

  /** HR Y-axis: snap to nice round numbers with 20 bpm spacing. */
  const hrAxisConfig = useMemo(() => {
    const hrValues = chartData.map((d) => d.hr).filter((v): v is number => v != null);
    if (hrValues.length === 0) return { domain: undefined, ticks: undefined };
    const min = Math.min(...hrValues);
    const max = Math.max(...hrValues);
    const lo = Math.floor(min / 20) * 20;
    const hi = Math.ceil(max / 20) * 20;
    return {
      domain: [lo, hi] as [number, number],
      ticks: niceTickRange(lo, hi, 20),
    };
  }, [chartData]);

  /** Pace / power / speed Y-axis: zoom to data range for pace; auto for others. */
  const secondaryAxisConfig = useMemo(() => {
    const vals = chartData
      .map((d) => d.secondary)
      .filter((v): v is number => v != null);
    if (vals.length === 0) return { domain: undefined, ticks: undefined, formatter: undefined };

    if (mode === "run") {
      // Pace values are in decimal minutes (e.g. 7.5 = 7:30/mi).
      const min = Math.min(...vals);
      const max = Math.max(...vals);
      // Pad by 0.5 min on each side, snapped to 0.5 boundaries
      const lo = Math.floor((min - 0.5) * 2) / 2;
      const hi = Math.ceil((max + 0.5) * 2) / 2;
      // Ticks every 0.5 min (30 seconds of pace)
      const ticks = niceTickRange(lo * 2, hi * 2, 1).map((v) => v / 2);
      return {
        domain: [lo, hi] as [number, number],
        ticks,
        formatter: formatPaceTick,
      };
    }
    // Power / speed: let Recharts auto-scale
    return { domain: undefined, ticks: undefined, formatter: undefined };
  }, [chartData, mode]);

  return (
    <Card className="!p-3">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-200">Analysis</h3>
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={() => setShowHR((v) => !v)}
            className={`px-2 py-1 rounded text-[10px] font-bold transition-colors ${
              showHR
                ? "bg-brand-red/20 text-brand-red"
                : "bg-cardBorder text-slate-500"
            }`}
          >
            HR
          </button>
          {mode !== "strength" && !ridePowerToggleHidden && (
            <button
              type="button"
              onClick={() => setShowSecondary((v) => !v)}
              className={`px-2 py-1 rounded text-[10px] font-bold transition-colors ${
                showSecondary
                  ? "bg-sky-400/20 text-sky-400"
                  : "bg-cardBorder text-slate-500"
              }`}
            >
              {secondaryName}
            </button>
          )}
        </div>
      </div>

      {!streams && !streamsLoading && (
        <div className="flex flex-col items-start gap-3 py-2">
          <p className="text-[11px] text-slate-500 leading-snug">
            {isApple ? (
              <>Per-sample heart rate from Apple Health.</>
            ) : (
              <>
                Per-sample heart rate
                {mode === "run" && " and pace"}
                {mode === "ride" && ", power, and speed"}. Fetched on demand
                from Strava.
                {streamsCached && " (Previously cached.)"}
              </>
            )}
          </p>
          {!isApple && (
            <button
              type="button"
              onClick={onLoadStreams}
              className="px-3 py-1.5 rounded-md text-xs font-medium bg-cardBorder text-slate-200 hover:bg-cardBorder/70 transition-colors"
            >
              Load Streams
            </button>
          )}
        </div>
      )}

      {streamsLoading && (
        <div className="text-xs text-slate-500 py-4">Loading streams…</div>
      )}

      {streamsError && (
        <div className="text-xs text-brand-red py-2">{streamsError}</div>
      )}

      {streams && chartData.length > 0 && (
        <div className="h-48 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={chartData}
              margin={{ top: 5, right: 0, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="colorHr" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#fb7185" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#fb7185" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="time"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: "#64748b" }}
                ticks={xTicks}
                type="number"
                domain={["dataMin", "dataMax"]}
              />
              {showSecondary && hasSecondary && mode !== "strength" && (
                <YAxis
                  yAxisId="left"
                  domain={secondaryAxisConfig.domain ?? ["auto", "auto"]}
                  ticks={secondaryAxisConfig.ticks}
                  tickFormatter={secondaryAxisConfig.formatter}
                  reversed={reverseSecondary}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 9, fill: "#38bdf8" }}
                  width={40}
                />
              )}
              {showHR && hasHR && (
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  domain={hrAxisConfig.domain}
                  ticks={hrAxisConfig.ticks}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fontSize: 9, fill: "#fb7185" }}
                  width={30}
                />
              )}
              <Tooltip
                cursor={{
                  stroke: "#475569",
                  strokeWidth: 1,
                  strokeDasharray: "4 4",
                }}
                contentStyle={{
                  background: "#0a0a0f",
                  border: "1px solid #222228",
                  borderRadius: 8,
                  fontSize: 11,
                }}
                formatter={(value: unknown, name: unknown) => {
                  if (name === "HR") return [`${value} bpm`, "HR"];
                  if (name === "Secondary" && mode === "run" && typeof value === "number") {
                    const m = Math.floor(value);
                    const s = Math.round((value - m) * 60)
                      .toString()
                      .padStart(2, "0");
                    return [`${m}:${s}${secondaryUnit}`, "Pace"];
                  }
                  if (name === "Secondary" && mode === "ride") {
                    return [`${value}${secondaryUnit}`, secondaryName];
                  }
                  return [String(value), String(name)];
                }}
                labelFormatter={(label) => `${label} min`}
              />
              {showHR && hasHR && (
                <Area
                  yAxisId="right"
                  type="monotone"
                  dataKey="hr"
                  name="HR"
                  stroke="#fb7185"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#colorHr)"
                  activeDot={{ r: 4, fill: "#fb7185" }}
                />
              )}
              {showSecondary && hasSecondary && mode !== "strength" && (
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="secondary"
                  name="Secondary"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  dot={false}
                  activeDot={false}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {streams && chartData.length === 0 && (
        isApple ? (
          <div className="py-2 space-y-1">
            <p className="text-xs text-slate-400">
              No per-sample heart rate data for this workout.
            </p>
            <p className="text-[10px] text-slate-500 leading-snug">
              Enable Workout Heart Rate Data in Health Auto Export →
              Workouts → Workout Heart Rate Data.
            </p>
          </div>
        ) : (
          <div className="text-xs text-slate-500 py-2">
            No stream data available.
          </div>
        )
      )}
    </Card>
  );
}
