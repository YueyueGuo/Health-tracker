import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { StrengthSessionDetail } from "../api/strength";

interface Props {
  session: StrengthSessionDetail;
}

/**
 * Session-wide HR curve with a dot marking each logged set's performed_at.
 * Caller is responsible for gating on ``session.hr_curve`` being present.
 */
export default function StrengthHrChart({ session }: Props) {
  const curve = session.hr_curve ?? [];
  if (curve.length === 0 || !session.activity_start_iso) return null;

  const data = curve.map(([t, bpm]) => ({ t, bpm }));
  const startMs = Date.parse(session.activity_start_iso);

  const setDots = session.sets
    .filter((s) => s.performed_at && typeof s.avg_hr === "number")
    .map((s) => ({
      id: s.id,
      t: (Date.parse(s.performed_at!) - startMs) / 1000,
      bpm: s.avg_hr as number,
    }));

  return (
    <div style={{ width: "100%", height: 220 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis
            dataKey="t"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={formatMinutes}
            stroke="var(--text-muted)"
            fontSize={11}
          />
          <YAxis
            domain={["dataMin - 5", "dataMax + 5"]}
            stroke="var(--text-muted)"
            fontSize={11}
            width={40}
          />
          <Tooltip
            contentStyle={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
            }}
            labelFormatter={(t) => formatMinutes(Number(t))}
            formatter={(value: unknown) => [`${Math.round(Number(value))} bpm`, "HR"]}
          />
          <Line
            type="monotone"
            dataKey="bpm"
            stroke="#ef4444"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          {setDots.map((d) => (
            <ReferenceDot
              key={d.id}
              x={d.t}
              y={d.bpm}
              r={4}
              fill="#ef4444"
              stroke="var(--bg-card)"
              strokeWidth={2}
              ifOverflow="extendDomain"
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function formatMinutes(t: number): string {
  const minutes = Math.floor(t / 60);
  const seconds = Math.floor(t % 60);
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}
