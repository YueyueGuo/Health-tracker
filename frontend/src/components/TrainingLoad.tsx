import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bike,
  ChevronDown,
  Dumbbell,
  Footprints,
  Heart,
  Sparkles,
} from "lucide-react";
import {
  Bar,
  BarChart,
  ComposedChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card } from "./ui/Card";
import { fetchActivities, type ActivitySummary } from "../api/activities";
import { fetchRecoveryTrends } from "../api/recovery";
import type { RecoveryTrend } from "../api/dashboard";
import { fetchSleepTrends, type SleepSession } from "../api/sleep";
import {
  fetchStrengthExercises,
  fetchStrengthProgression,
  fetchStrengthSessions,
  type ProgressionPoint,
  type StrengthSession,
} from "../api/strength";
import { useApi } from "../hooks/useApi";
import { useUnits, type UnitSystem } from "../hooks/useUnits";

type TimeRange = "1W" | "1M" | "3M" | "YTD";
type CardioActivity = "Run" | "Ride";
type CardioWorkoutType = "All" | "Long" | "VO2 Max" | "Base";

interface CardioPoint {
  id: number;
  date: string;
  dateLabel: string;
  activity: CardioActivity;
  type: CardioWorkoutType;
  distance: number;
  tss: number | null;
  pace: number | null;
  np: number | null;
}

interface WeeklyRecoveryPoint {
  week: string;
  weekStart: string;
  tss: number;
  recovery: number | null;
  hrv: number | null;
  rhr: number | null;
  sleepDur: number | null;
  sleepNeed: number | null;
}

interface TooltipEntry {
  name?: string;
  value?: number | string | null;
  color?: string;
  dataKey?: string;
}

interface TrendTooltipProps {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string;
}

const TIME_RANGES: TimeRange[] = ["1W", "1M", "3M", "YTD"];
const WORKOUT_TYPES: CardioWorkoutType[] = ["All", "Long", "VO2 Max", "Base"];
const RUN_SPORTS = new Set(["run", "trailrun", "virtualrun"]);
const RIDE_SPORTS = new Set([
  "ride",
  "virtualride",
  "gravelride",
  "mountainbikeride",
  "ebikeride",
]);
const METERS_PER_MILE = 1609.344;
const KG_TO_LB = 2.2046226218;

export default function TrainingLoad() {
  const { units } = useUnits();
  const [timeRange, setTimeRange] = useState<TimeRange>("3M");
  const [cardioActivity, setCardioActivity] = useState<CardioActivity>("Run");
  const [cardioWorkoutType, setCardioWorkoutType] =
    useState<CardioWorkoutType>("All");
  const [selectedExercise, setSelectedExercise] = useState("");

  const days = useMemo(() => daysForRange(timeRange), [timeRange]);
  const activities = useApi(
    ["activities", "list", { days, limit: 200 }],
    () => fetchActivities({ days, limit: 200 }),
  );
  const recovery = useApi(["recovery", "trends", days], () =>
    fetchRecoveryTrends(days),
  );
  const sleep = useApi(["sleep", "trends", days], () => fetchSleepTrends(days));
  const strengthSessions = useApi(["strength", "sessions", 200], () =>
    fetchStrengthSessions(200),
  );
  const strengthExercises = useApi(["strength", "exercises"], () =>
    fetchStrengthExercises(),
  );

  useEffect(() => {
    if (!selectedExercise && strengthExercises.data?.length) {
      setSelectedExercise(strengthExercises.data[0]);
    }
  }, [selectedExercise, strengthExercises.data]);

  const strengthProgression = useApi(
    ["strength", "progression", selectedExercise, days],
    () =>
      selectedExercise
        ? fetchStrengthProgression(selectedExercise, days)
        : Promise.resolve([]),
    { enabled: Boolean(selectedExercise) },
  );

  const cardioData = useMemo(
    () => buildCardioData(activities.data ?? [], units),
    [activities.data, units]
  );
  const filteredCardioData = useMemo(
    () =>
      cardioData.filter(
        (point) =>
          point.activity === cardioActivity &&
          (cardioWorkoutType === "All" || point.type === cardioWorkoutType)
      ),
    [cardioActivity, cardioData, cardioWorkoutType]
  );
  const latestCardio =
    filteredCardioData[filteredCardioData.length - 1] ?? null;
  const strengthData = useMemo(
    () => buildStrengthData(strengthProgression.data ?? [], units),
    [strengthProgression.data, units]
  );
  const weeklyVolume = useMemo(
    () => buildStrengthWeeklyVolume(strengthSessions.data ?? [], units),
    [strengthSessions.data, units]
  );
  const weeklyRecovery = useMemo(
    () =>
      buildWeeklyRecovery(
        activities.data ?? [],
        recovery.data ?? [],
        sleep.data ?? []
      ),
    [activities.data, recovery.data, sleep.data]
  );
  const macroSummary = useMemo(
    () =>
      buildMacroSummary({
        cardioData,
        strengthData,
        weeklyRecovery,
        timeRange,
        units,
      }),
    [cardioData, strengthData, timeRange, units, weeklyRecovery]
  );

  const loading =
    activities.loading ||
    recovery.loading ||
    sleep.loading ||
    strengthSessions.loading ||
    strengthExercises.loading ||
    strengthProgression.loading;
  const error =
    activities.error ||
    recovery.error ||
    sleep.error ||
    strengthSessions.error ||
    strengthExercises.error ||
    strengthProgression.error;

  return (
    <div className="pb-24 pt-4 animate-in fade-in duration-300">
      <div className="px-1 mb-4">
        <div className="flex items-center justify-between mb-4 gap-3">
          <h1 className="text-2xl font-bold text-white tracking-tight">
            Trends
          </h1>
          <div className="flex bg-cardBorder/30 rounded-lg p-1">
            {TIME_RANGES.map((range) => (
              <button
                key={range}
                type="button"
                onClick={() => setTimeRange(range)}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  timeRange === range
                    ? "bg-cardBorder text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {range}
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading && (
        <div className="text-center py-3 text-slate-500 text-sm">
          Loading trends…
        </div>
      )}
      {error && (
        <div className="mb-4 rounded-xl border border-brand-red/30 bg-brand-red/10 px-4 py-3 text-sm text-brand-red">
          {error}
        </div>
      )}

      <div className="space-y-4">
        <Card className="relative overflow-hidden p-4 group border-brand-green/20">
          <div className="absolute inset-0 bg-brand-green/5 pointer-events-none" />
          <div className="relative z-10">
            <div className="flex items-center gap-1.5 mb-3">
              <Sparkles size={14} className="text-brand-green" />
              <h3 className="text-xs font-semibold text-brand-green uppercase tracking-wider">
                Macro Analysis
              </h3>
            </div>
            <p className="text-sm text-slate-200 leading-relaxed">
              {macroSummary}
            </p>
          </div>
        </Card>

        <section className="space-y-3">
          <div className="flex items-center gap-2 px-1">
            <Activity size={16} className="text-brand-green" />
            <h2 className="text-lg font-bold text-white">Cardio</h2>
          </div>

          <div className="flex items-center justify-between gap-3 px-1">
            <div className="flex bg-cardBorder/30 rounded-lg p-1">
              <button
                type="button"
                onClick={() => setCardioActivity("Run")}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  cardioActivity === "Run"
                    ? "bg-brand-green text-dashboard shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Footprints size={12} /> Run
              </button>
              <button
                type="button"
                onClick={() => setCardioActivity("Ride")}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  cardioActivity === "Ride"
                    ? "bg-orange-500 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Bike size={12} /> Ride
              </button>
            </div>

            <div className="relative">
              <select
                value={cardioWorkoutType}
                onChange={(e) =>
                  setCardioWorkoutType(e.target.value as CardioWorkoutType)
                }
                aria-label="Cardio workout type"
                className="appearance-none bg-cardBorder/30 text-slate-200 text-xs font-medium py-1.5 pl-3 pr-8 rounded-lg focus:outline-none focus:ring-1 focus:ring-brand-green"
              >
                {WORKOUT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type === "Long"
                      ? `Long ${cardioActivity === "Run" ? "Runs" : "Rides"}`
                      : type === "Base"
                        ? "Base / Easy"
                        : type === "All"
                          ? "All Workouts"
                          : type}
                  </option>
                ))}
              </select>
              <ChevronDown
                size={12}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none"
              />
            </div>
          </div>

          <Card className="p-4">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-slate-200">
                {cardioWorkoutType === "All" ? "Total" : cardioWorkoutType}{" "}
                Distance Progression
              </h3>
              <p className="text-2xl font-bold text-white mt-1">
                {latestCardio
                  ? `${latestCardio.distance.toFixed(1)}`
                  : "—"}{" "}
                <span className="text-sm text-slate-500 font-normal">
                  {distanceUnit(units)} latest
                </span>
              </p>
            </div>
            {filteredCardioData.length > 0 ? (
              <div className="h-48 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={filteredCardioData}
                    margin={{ top: 0, right: 0, left: -25, bottom: 0 }}
                  >
                    <XAxis
                      dataKey="dateLabel"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                      dy={10}
                    />
                    <YAxis
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                    />
                    <Tooltip content={<TrendTooltip units={units} />} />
                    <Bar
                      dataKey="distance"
                      name="Distance"
                      fill={cardioActivity === "Run" ? "#34d399" : "#f97316"}
                      radius={[4, 4, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState text="No matching cardio workouts in this range." />
            )}
          </Card>

          <Card className="p-4">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-slate-200">
                {cardioActivity === "Run" && cardioWorkoutType === "VO2 Max"
                  ? "Pace Progression"
                  : cardioActivity === "Ride" &&
                      cardioWorkoutType === "VO2 Max"
                    ? "Power Progression"
                    : "Training Stress Score"}
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                {cardioActivity === "Run" && cardioWorkoutType === "VO2 Max"
                  ? "Lower is faster."
                  : cardioActivity === "Ride" &&
                      cardioWorkoutType === "VO2 Max"
                    ? "Higher is more powerful."
                    : "Cardiovascular load over time."}
              </p>
            </div>
            {filteredCardioData.length > 0 ? (
              <div className="h-48 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={filteredCardioData}
                    margin={{ top: 5, right: 5, left: -25, bottom: 0 }}
                  >
                    <XAxis
                      dataKey="dateLabel"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                      dy={10}
                    />
                    <YAxis
                      domain={["auto", "auto"]}
                      reversed={
                        cardioActivity === "Run" &&
                        cardioWorkoutType === "VO2 Max"
                      }
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                    />
                    <Tooltip content={<TrendTooltip units={units} />} />
                    <Line
                      type="monotone"
                      dataKey={cardioMetricKey(
                        cardioActivity,
                        cardioWorkoutType
                      )}
                      name={cardioMetricName(
                        cardioActivity,
                        cardioWorkoutType
                      )}
                      stroke="#38bdf8"
                      strokeWidth={3}
                      connectNulls
                      dot={{ fill: "#38bdf8", strokeWidth: 2, r: 4 }}
                      activeDot={{ r: 6 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState text="No matching performance data in this range." />
            )}
          </Card>
        </section>

        <section className="space-y-3">
          <div className="flex items-center gap-2 px-1">
            <Dumbbell size={16} className="text-slate-300" />
            <h2 className="text-lg font-bold text-white">Strength</h2>
          </div>

          <Card className="p-4">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <h3 className="text-sm font-semibold text-slate-200">
                  Max Weight Progression
                </h3>
                <p className="text-2xl font-bold text-white mt-1">
                  {strengthData[
                    strengthData.length - 1
                  ]?.maxWeight.toFixed(0) ?? "—"}{" "}
                  <span className="text-sm text-slate-500 font-normal">
                    {weightUnit(units)}
                  </span>
                </p>
              </div>
              <div className="relative">
                <select
                  value={selectedExercise}
                  onChange={(e) => setSelectedExercise(e.target.value)}
                  aria-label="Strength exercise"
                  className="appearance-none max-w-[170px] bg-cardBorder/50 py-1.5 pl-3 pr-8 rounded-md text-xs font-medium text-slate-300 hover:bg-cardBorder transition-colors focus:outline-none focus:ring-1 focus:ring-brand-green"
                >
                  {strengthExercises.data?.length ? (
                    strengthExercises.data.map((exercise) => (
                      <option key={exercise} value={exercise}>
                        {exercise}
                      </option>
                    ))
                  ) : (
                    <option value="">No exercises</option>
                  )}
                </select>
                <ChevronDown
                  size={14}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none"
                />
              </div>
            </div>
            {strengthData.length > 0 ? (
              <div className="h-48 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={strengthData}
                    margin={{ top: 5, right: 5, left: -20, bottom: 0 }}
                  >
                    <XAxis
                      dataKey="dateLabel"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                      dy={10}
                    />
                    <YAxis
                      domain={["dataMin - 20", "dataMax + 20"]}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                    />
                    <Tooltip content={<TrendTooltip units={units} />} />
                    <Line
                      type="stepAfter"
                      dataKey="maxWeight"
                      name="Max Weight"
                      stroke="#e2e8f0"
                      strokeWidth={3}
                      dot={{ fill: "#e2e8f0", r: 4 }}
                      activeDot={{ r: 6 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState text="No strength progression for this exercise yet." />
            )}
          </Card>

          <Card className="p-4">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-slate-200">
                Weekly Volume
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                Total weight moved across logged strength sessions.
              </p>
            </div>
            {weeklyVolume.length > 0 ? (
              <div className="h-48 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={weeklyVolume}
                    margin={{ top: 0, right: 0, left: -10, bottom: 0 }}
                  >
                    <XAxis
                      dataKey="week"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                      dy={10}
                    />
                    <YAxis
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                      tickFormatter={(value: number) =>
                        `${Math.round(value / 1000)}k`
                      }
                    />
                    <Tooltip content={<TrendTooltip units={units} />} />
                    <Bar
                      dataKey="volume"
                      name="Volume"
                      fill="#475569"
                      radius={[4, 4, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState text="No strength volume logged yet." />
            )}
          </Card>
        </section>

        <section className="space-y-3">
          <div className="flex items-center gap-2 px-1">
            <Heart size={16} className="text-brand-red" />
            <h2 className="text-lg font-bold text-white">Recovery</h2>
          </div>

          <Card className="p-4">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-slate-200">
                Training Load vs. Recovery
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                How weekly TSS lines up with average recovery score.
              </p>
            </div>
            {weeklyRecovery.length > 0 ? (
              <>
                <div className="h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart
                      data={weeklyRecovery}
                      margin={{ top: 5, right: 0, left: -25, bottom: 0 }}
                    >
                      <XAxis
                        dataKey="week"
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 10, fill: "#64748b" }}
                        dy={10}
                      />
                      <YAxis
                        yAxisId="left"
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 10, fill: "#64748b" }}
                      />
                      <YAxis
                        yAxisId="right"
                        orientation="right"
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 10, fill: "#64748b" }}
                      />
                      <Tooltip content={<TrendTooltip units={units} />} />
                      <Bar
                        yAxisId="left"
                        dataKey="tss"
                        name="Weekly TSS"
                        fill="#f97316"
                        fillOpacity={0.3}
                        radius={[4, 4, 0, 0]}
                      />
                      <Line
                        yAxisId="right"
                        type="monotone"
                        dataKey="recovery"
                        name="Avg Recovery"
                        stroke="#34d399"
                        strokeWidth={3}
                        connectNulls
                        dot={{ fill: "#34d399", r: 4 }}
                        activeDot={{ r: 6 }}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
                <LegendRow
                  items={[
                    {
                      label: "Weekly TSS",
                      className: "w-2.5 h-2.5 rounded-sm bg-orange-500 opacity-30",
                    },
                    {
                      label: "Avg Recovery",
                      className: "w-2.5 h-2.5 rounded-full bg-brand-green",
                    },
                  ]}
                />
              </>
            ) : (
              <EmptyState text="No recovery trend data in this range." />
            )}
          </Card>

          <Card className="p-4">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-slate-200">
                Nervous System Adaptation
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                Long-term trends in HRV and resting heart rate.
              </p>
            </div>
            {weeklyRecovery.some((point) => point.hrv || point.rhr) ? (
              <>
                <div className="h-48 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart
                      data={weeklyRecovery}
                      margin={{ top: 5, right: 0, left: -25, bottom: 0 }}
                    >
                      <XAxis
                        dataKey="week"
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 10, fill: "#64748b" }}
                        dy={10}
                      />
                      <YAxis
                        yAxisId="left"
                        domain={["dataMin - 5", "dataMax + 5"]}
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 10, fill: "#64748b" }}
                      />
                      <YAxis
                        yAxisId="right"
                        orientation="right"
                        domain={["dataMin - 5", "dataMax + 5"]}
                        axisLine={false}
                        tickLine={false}
                        tick={{ fontSize: 10, fill: "#64748b" }}
                      />
                      <Tooltip content={<TrendTooltip units={units} />} />
                      <Line
                        yAxisId="left"
                        type="monotone"
                        dataKey="hrv"
                        name="HRV"
                        stroke="#38bdf8"
                        strokeWidth={2}
                        connectNulls
                        dot={false}
                        activeDot={{ r: 5 }}
                      />
                      <Line
                        yAxisId="right"
                        type="monotone"
                        dataKey="rhr"
                        name="Resting HR"
                        stroke="#fb7185"
                        strokeWidth={2}
                        connectNulls
                        dot={false}
                        activeDot={{ r: 5 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <LegendRow
                  items={[
                    {
                      label: "HRV",
                      className: "w-2.5 h-1 rounded-sm bg-sky-400",
                    },
                    {
                      label: "Resting HR",
                      className: "w-2.5 h-1 rounded-sm bg-brand-red",
                    },
                  ]}
                />
              </>
            ) : (
              <EmptyState text="No HRV or resting heart-rate trend data yet." />
            )}
          </Card>

          <Card className="p-4">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-slate-200">
                Sleep Duration vs. Need
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                Tracking how well sleep time meets estimated sleep need.
              </p>
            </div>
            {weeklyRecovery.some((point) => point.sleepDur) ? (
              <div className="h-48 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart
                    data={weeklyRecovery}
                    margin={{ top: 5, right: 0, left: -25, bottom: 0 }}
                  >
                    <XAxis
                      dataKey="week"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                      dy={10}
                    />
                    <YAxis
                      domain={[5, 10]}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                    />
                    <Tooltip content={<TrendTooltip units={units} />} />
                    <Bar
                      dataKey="sleepDur"
                      name="Sleep"
                      fill="#818cf8"
                      radius={[4, 4, 0, 0]}
                    />
                    <Line
                      type="step"
                      dataKey="sleepNeed"
                      name="Need"
                      stroke="#cbd5e1"
                      strokeWidth={2}
                      strokeDasharray="4 4"
                      connectNulls
                      dot={false}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState text="No sleep duration data in this range." />
            )}
          </Card>
        </section>
      </div>
    </div>
  );
}

function TrendTooltip({
  active,
  payload,
  label,
  units,
}: TrendTooltipProps & { units: UnitSystem }) {
  if (!active || !payload?.length) return null;

  return (
    <div className="bg-dashboard border border-cardBorder p-2 rounded-lg shadow-xl">
      <p className="text-[10px] text-slate-400 mb-1">{label}</p>
      {payload.map((entry, index) => (
        <div
          key={`${entry.name ?? entry.dataKey ?? "value"}-${index}`}
          className="flex items-center gap-2 text-xs font-bold"
          style={{ color: entry.color }}
        >
          <span>{entry.name ?? entry.dataKey}:</span>
          <span>{formatTooltipValue(entry, units)}</span>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="py-10 text-center text-sm text-slate-500">{text}</div>;
}

function LegendRow({
  items,
}: {
  items: Array<{ label: string; className: string }>;
}) {
  return (
    <div className="flex justify-center gap-4 mt-3">
      {items.map((item) => (
        <div
          key={item.label}
          className="flex items-center gap-1.5 text-[10px] text-slate-400 font-medium"
        >
          <div className={item.className} />
          {item.label}
        </div>
      ))}
    </div>
  );
}

function daysForRange(range: TimeRange): number {
  if (range === "1W") return 7;
  if (range === "1M") return 30;
  if (range === "3M") return 90;
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 1);
  return Math.max(1, Math.ceil((now.getTime() - start.getTime()) / 86400000) + 1);
}

function buildCardioData(
  activities: ActivitySummary[],
  units: UnitSystem
): CardioPoint[] {
  return [...activities]
    .filter((activity) => toCardioActivity(activity.sport_type) !== null)
    .sort((a, b) => dateValue(a) - dateValue(b))
    .map((activity) => {
      const cardioActivity = toCardioActivity(activity.sport_type) ?? "Run";
      return {
        id: activity.id,
        date: activity.start_date_local ?? activity.start_date ?? "",
        dateLabel: shortDate(activity.start_date_local ?? activity.start_date),
        activity: cardioActivity,
        type: toWorkoutType(activity),
        distance: convertDistance(activity.distance ?? 0, units),
        tss: activity.suffer_score ?? estimatedStress(activity),
        pace:
          cardioActivity === "Run"
            ? paceMinutes(activity.average_speed, units)
            : null,
        np:
          cardioActivity === "Ride"
            ? activity.weighted_avg_power ?? activity.average_power
            : null,
      };
    });
}

function buildStrengthData(
  progression: ProgressionPoint[],
  units: UnitSystem
) {
  return progression.map((point) => ({
    date: point.date,
    dateLabel: shortDate(point.date),
    maxWeight: convertWeight(point.max_weight_kg, units),
    estOneRepMax: convertWeight(point.est_1rm_kg, units),
    volume: convertWeight(point.total_volume_kg, units),
  }));
}

function buildStrengthWeeklyVolume(
  sessions: StrengthSession[],
  units: UnitSystem
) {
  const byWeek = new Map<string, { week: string; weekStart: string; volume: number }>();
  for (const session of sessions) {
    const weekStart = isoWeekStart(session.date);
    const existing =
      byWeek.get(weekStart) ?? {
        week: weekLabel(weekStart),
        weekStart,
        volume: 0,
      };
    existing.volume += convertWeight(session.total_volume_kg, units);
    byWeek.set(weekStart, existing);
  }
  return [...byWeek.values()].sort((a, b) =>
    a.weekStart.localeCompare(b.weekStart)
  );
}

function buildWeeklyRecovery(
  activities: ActivitySummary[],
  recovery: RecoveryTrend[],
  sleep: SleepSession[]
): WeeklyRecoveryPoint[] {
  const weeks = new Map<
    string,
    {
      tss: number;
      recovery: number[];
      hrv: number[];
      rhr: number[];
      sleepDur: number[];
      sleepNeed: number[];
    }
  >();

  const ensure = (date: string) => {
    const weekStart = isoWeekStart(date);
    const bucket =
      weeks.get(weekStart) ??
      {
        tss: 0,
        recovery: [],
        hrv: [],
        rhr: [],
        sleepDur: [],
        sleepNeed: [],
      };
    weeks.set(weekStart, bucket);
    return bucket;
  };

  for (const activity of activities) {
    const date = activity.start_date_local ?? activity.start_date;
    if (!date) continue;
    ensure(date).tss += activity.suffer_score ?? estimatedStress(activity) ?? 0;
  }

  for (const row of recovery) {
    const bucket = ensure(row.date);
    pushNumber(bucket.recovery, row.recovery_score);
    pushNumber(bucket.hrv, row.hrv);
    pushNumber(bucket.rhr, row.resting_hr);
  }

  for (const row of sleep) {
    const bucket = ensure(row.date);
    if (row.total_duration != null) {
      bucket.sleepDur.push(row.total_duration / 60);
    }
    const need = sleepNeedHours(row);
    if (need != null) bucket.sleepNeed.push(need);
    pushNumber(bucket.hrv, row.hrv);
    pushNumber(bucket.rhr, row.avg_hr);
  }

  return [...weeks.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([weekStart, bucket]) => ({
      week: weekLabel(weekStart),
      weekStart,
      tss: Math.round(bucket.tss),
      recovery: average(bucket.recovery),
      hrv: average(bucket.hrv),
      rhr: average(bucket.rhr),
      sleepDur: average(bucket.sleepDur),
      sleepNeed: average(bucket.sleepNeed),
    }));
}

function buildMacroSummary({
  cardioData,
  strengthData,
  weeklyRecovery,
  timeRange,
  units,
}: {
  cardioData: CardioPoint[];
  strengthData: ReturnType<typeof buildStrengthData>;
  weeklyRecovery: WeeklyRecoveryPoint[];
  timeRange: TimeRange;
  units: UnitSystem;
}) {
  const parts: string[] = [];
  const hrvDelta = delta(firstNumber(weeklyRecovery, "hrv"), lastNumber(weeklyRecovery, "hrv"));
  const rhrDelta = delta(firstNumber(weeklyRecovery, "rhr"), lastNumber(weeklyRecovery, "rhr"));
  const tssDelta = delta(firstNumber(weeklyRecovery, "tss"), lastNumber(weeklyRecovery, "tss"));
  const runDistances = cardioData.filter((point) => point.activity === "Run");
  const strengthDelta = delta(
    strengthData[0]?.maxWeight ?? null,
    strengthData[strengthData.length - 1]?.maxWeight ?? null
  );

  if (hrvDelta != null || rhrDelta != null) {
    parts.push(
      `Over ${timeRange}, HRV is ${formatSigned(hrvDelta, "ms")} and resting heart rate is ${formatSigned(rhrDelta, "bpm")}.`
    );
  }
  if (tssDelta != null) {
    parts.push(`Weekly training stress is ${formatSigned(tssDelta, "TSS")}.`);
  }
  if (runDistances.length >= 2) {
    const distanceDelta =
      runDistances[runDistances.length - 1].distance - runDistances[0].distance;
    parts.push(
      `Run distance is ${formatSigned(distanceDelta, distanceUnit(units))} from the first logged run in this range.`
    );
  }
  if (strengthDelta != null) {
    parts.push(
      `Selected lift max is ${formatSigned(strengthDelta, weightUnit(units))}.`
    );
  }

  return parts.length
    ? parts.join(" ")
    : "Add more cardio, strength, sleep, and recovery history to unlock a richer trend read.";
}

function toCardioActivity(sportType: string): CardioActivity | null {
  const normalized = sportType.toLowerCase();
  if (RUN_SPORTS.has(normalized)) return "Run";
  if (RIDE_SPORTS.has(normalized)) return "Ride";
  return null;
}

function toWorkoutType(activity: ActivitySummary): CardioWorkoutType {
  const type = activity.classification_type;
  if (type === "intervals" || type === "race") return "VO2 Max";
  if (type === "endurance") return "Long";
  if (type === "easy" || type === "recovery") return "Base";
  if ((activity.moving_time ?? 0) >= 5400 || (activity.distance ?? 0) >= 16000) {
    return "Long";
  }
  return "Base";
}

function cardioMetricKey(
  activity: CardioActivity,
  workoutType: CardioWorkoutType
) {
  if (activity === "Run" && workoutType === "VO2 Max") return "pace";
  if (activity === "Ride" && workoutType === "VO2 Max") return "np";
  return "tss";
}

function cardioMetricName(
  activity: CardioActivity,
  workoutType: CardioWorkoutType
) {
  if (activity === "Run" && workoutType === "VO2 Max") return "Pace";
  if (activity === "Ride" && workoutType === "VO2 Max") return "Power";
  return "TSS";
}

function formatTooltipValue(entry: TooltipEntry, units: UnitSystem): string {
  if (entry.value == null || entry.value === "") return "—";
  const value =
    typeof entry.value === "number" ? entry.value : Number(entry.value);
  if (Number.isNaN(value)) return String(entry.value);
  if (entry.name === "Pace") return formatPaceMinutes(value, units);
  if (entry.name === "Power") return `${Math.round(value)}W`;
  if (entry.name === "Distance") return `${value.toFixed(1)} ${distanceUnit(units)}`;
  if (entry.name === "Sleep" || entry.name === "Need") return formatHours(value);
  if (entry.name === "Max Weight" || entry.name === "Volume") {
    return `${Math.round(value).toLocaleString()} ${weightUnit(units)}`;
  }
  if (entry.name?.includes("Recovery")) return `${Math.round(value)}%`;
  if (entry.name === "HRV") return `${Math.round(value)} ms`;
  if (entry.name === "Resting HR") return `${Math.round(value)} bpm`;
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function estimatedStress(activity: ActivitySummary): number | null {
  if (activity.moving_time && activity.average_hr) {
    return Math.round((activity.moving_time / 60) * (activity.average_hr / 180));
  }
  return null;
}

function paceMinutes(speedMps: number | null | undefined, units: UnitSystem) {
  if (!speedMps || speedMps <= 0) return null;
  const meters = units === "imperial" ? METERS_PER_MILE : 1000;
  return meters / speedMps / 60;
}

function formatPaceMinutes(value: number, units: UnitSystem): string {
  const minutes = Math.floor(value);
  const seconds = Math.round((value - minutes) * 60);
  return `${minutes}:${seconds.toString().padStart(2, "0")}/${distanceUnit(units)}`;
}

function convertDistance(meters: number, units: UnitSystem): number {
  return units === "imperial" ? meters / METERS_PER_MILE : meters / 1000;
}

function convertWeight(kg: number, units: UnitSystem): number {
  return units === "imperial" ? kg * KG_TO_LB : kg;
}

function distanceUnit(units: UnitSystem): string {
  return units === "imperial" ? "mi" : "km";
}

function weightUnit(units: UnitSystem): string {
  return units === "imperial" ? "lbs" : "kg";
}

function sleepNeedHours(row: SleepSession): number | null {
  if (row.sleep_need_baseline_min == null) return null;
  return ((row.sleep_need_baseline_min ?? 0) + (row.sleep_debt_min ?? 0)) / 60;
}

function pushNumber(values: number[], value: number | null | undefined) {
  if (value != null) values.push(value);
}

function average(values: number[]): number | null {
  if (values.length === 0) return null;
  return round(values.reduce((sum, value) => sum + value, 0) / values.length, 1);
}

function delta(first: number | null, last: number | null): number | null {
  if (first == null || last == null) return null;
  return round(last - first, 1);
}

function firstNumber(
  rows: WeeklyRecoveryPoint[],
  key: keyof WeeklyRecoveryPoint
): number | null {
  for (const row of rows) {
    const value = row[key];
    if (typeof value === "number") return value;
  }
  return null;
}

function lastNumber(
  rows: WeeklyRecoveryPoint[],
  key: keyof WeeklyRecoveryPoint
): number | null {
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const value = rows[i][key];
    if (typeof value === "number") return value;
  }
  return null;
}

function formatSigned(value: number | null, unit: string): string {
  if (value == null) return "not yet available";
  if (value === 0) return `flat at 0 ${unit}`;
  const direction = value > 0 ? "up" : "down";
  return `${direction} ${Math.abs(value).toFixed(Math.abs(value) < 10 ? 1 : 0)} ${unit}`;
}

function formatHours(hours: number): string {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  return `${h}h ${m}m`;
}

function round(value: number, precision: number): number {
  const factor = 10 ** precision;
  return Math.round(value * factor) / factor;
}

function dateValue(activity: ActivitySummary): number {
  const date = activity.start_date_local ?? activity.start_date;
  return date ? new Date(date).getTime() : 0;
}

function shortDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function isoWeekStart(value: string): string {
  const date = new Date(value);
  const local = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const day = local.getDay() || 7;
  local.setDate(local.getDate() - day + 1);
  return local.toISOString().slice(0, 10);
}

function weekLabel(weekStart: string): string {
  return shortDate(weekStart);
}
