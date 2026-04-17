import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import type { ProgressionPoint } from "../api/strength";

interface Props {
  data: ProgressionPoint[];
  exerciseName: string;
}

/**
 * Weight-over-time line chart for a single exercise. Plots both the
 * heaviest set on that date (`max_weight_kg`) and the best Epley 1RM
 * estimate (`est_1rm_kg`) so the user can see strength trend even
 * when they vary rep schemes.
 */
export default function StrengthProgressionChart({ data, exerciseName }: Props) {
  if (!data || data.length === 0) {
    return (
      <div style={{ color: "var(--text-muted)", padding: 24, textAlign: "center" }}>
        No progression data yet for <strong>{exerciseName}</strong>.
      </div>
    );
  }

  const chartData = data.map((p) => ({
    date: formatShortDate(p.date),
    max_weight: p.max_weight_kg,
    est_1rm: p.est_1rm_kg,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={12} />
        <YAxis
          stroke="var(--text-muted)"
          label={{
            value: "kg",
            angle: -90,
            position: "insideLeft",
            fill: "var(--text-muted)",
            fontSize: 12,
          }}
        />
        <Tooltip
          contentStyle={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
          }}
        />
        <Legend />
        <Line
          type="monotone"
          dataKey="max_weight"
          stroke="#6366f1"
          strokeWidth={2}
          dot={{ r: 3 }}
          name="Top set (kg)"
          connectNulls
        />
        <Line
          type="monotone"
          dataKey="est_1rm"
          stroke="#22c55e"
          strokeWidth={2}
          dot={{ r: 3 }}
          name="Est. 1RM (kg)"
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

function formatShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
