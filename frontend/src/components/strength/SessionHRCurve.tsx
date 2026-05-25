import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card } from "../ui/Card";
import type {
  SegmentationStatus,
  StrengthSegmentMarker,
} from "../../api/strength";

interface Props {
  hrCurve: Array<[number, number]> | null;
  segmentMarkers: StrengthSegmentMarker[] | null;
  segmentationStatus: SegmentationStatus | null;
}

interface ChartDatum {
  time: number;
  hr: number;
}

function formatMmSs(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function SessionHRCurve({
  hrCurve,
  segmentMarkers,
  segmentationStatus,
}: Props) {
  const data = useMemo<ChartDatum[]>(() => {
    if (!hrCurve) return [];
    return hrCurve.map(([t, bpm]) => ({ time: t, hr: bpm }));
  }, [hrCurve]);

  // Apple Health summary-only: show a banner explaining the missing curve.
  if (segmentationStatus === "no_curve") {
    return (
      <Card className="!p-3" data-testid="hr-curve-no-curve">
        <h3 className="text-sm font-semibold text-slate-200 mb-2">
          Heart-rate curve
        </h3>
        <p className="text-xs text-slate-400">
          This workout reports session-level HR but no time series — curve
          and per-set HR can't be derived.
        </p>
      </Card>
    );
  }

  if (!hrCurve || data.length === 0) {
    return null;
  }

  return (
    <Card className="!p-3" data-testid="hr-curve">
      <h3 className="text-sm font-semibold text-slate-200 mb-2">
        Heart-rate curve
      </h3>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 5, right: 8, left: 0, bottom: 0 }}
          >
            <CartesianGrid stroke="#222228" vertical={false} />
            <XAxis
              dataKey="time"
              type="number"
              domain={["dataMin", "dataMax"]}
              axisLine={false}
              tickLine={false}
              tick={{ fontSize: 10, fill: "#64748b" }}
              tickFormatter={(v: number) => formatMmSs(v)}
              minTickGap={40}
            />
            <YAxis
              domain={["dataMin - 5", "dataMax + 5"]}
              axisLine={false}
              tickLine={false}
              tick={{ fontSize: 10, fill: "#fb7185" }}
              width={32}
            />
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
              formatter={(value: unknown) => [`${value} bpm`, "HR"]}
              labelFormatter={(label) =>
                typeof label === "number" ? formatMmSs(label) : String(label)
              }
            />
            {segmentMarkers?.map((m) => (
              <ReferenceArea
                key={`seg-${m.set_number}-${m.start_sec}`}
                x1={m.start_sec}
                x2={m.end_sec}
                strokeOpacity={0}
                fill="#fb7185"
                fillOpacity={0.12}
                label={{
                  value: `Set ${m.set_number}`,
                  position: "insideTop",
                  fontSize: 9,
                  fill: "#fb7185",
                }}
              />
            ))}
            <Line
              type="monotone"
              dataKey="hr"
              name="HR"
              stroke="#fb7185"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: "#fb7185" }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
