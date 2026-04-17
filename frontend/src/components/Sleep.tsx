import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useState } from "react";
import { useApi } from "../hooks/useApi";
import {
  fetchSleepSessions,
  fetchSleepTrends,
  fetchLatestSleep,
  SleepSession,
  WakeEvent,
} from "../api/sleep";

// Stage palette picked for hue separation rather than pretty variance on
// a single hue: deep = navy (darkest blue), REM = teal/cyan (cool), light
// = warm tan (warm, low-sat), awake = red (hot). Each pair is distinct
// in both hue and luminance so the stacked bars read at a glance.
const STAGE_COLORS = {
  deep: "#1e3a8a",   // navy
  rem: "#14b8a6",    // teal
  light: "#d4a574",  // warm sand
  awake: "#ef4444",  // red
};

export default function Sleep() {
  const [days, setDays] = useState(30);

  const { data: trends, loading: trendsLoading, error: trendsError } = useApi(
    () => fetchSleepTrends(days),
    [days]
  );
  const { data: sessions, loading: sessionsLoading } = useApi(
    () => fetchSleepSessions(30),
    []
  );
  const { data: latest, loading: latestLoading } = useApi(fetchLatestSleep, []);

  if (trendsLoading || sessionsLoading || latestLoading) {
    return <div className="loading">Loading sleep data...</div>;
  }
  if (trendsError) return <div className="error">{trendsError}</div>;

  if ((!trends || trends.length === 0) && !latest) {
    return (
      <div>
        <div className="page-header">
          <h1>Sleep</h1>
          <p>No sleep data available. Connect Eight Sleep to get started.</p>
        </div>
      </div>
    );
  }

  const scoreChartData = (trends || []).map((s) => ({
    date: formatShortDate(s.date),
    score: s.sleep_score,
    fitness: s.sleep_fitness_score,
  }));

  // Stages chart is limited to last 30 days regardless of the trend selector
  const stagesSource = (trends || []).slice(-30);
  const stagesChartData = stagesSource.map((s) => ({
    date: formatShortDate(s.date),
    deep: s.deep_sleep ?? 0,
    rem: s.rem_sleep ?? 0,
    light: s.light_sleep ?? 0,
    awake: s.awake_time ?? 0,
  }));

  // Recent nights: newest-first, cap to 14 for readability
  const recentNights = [...(sessions || [])]
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 14);

  return (
    <div>
      <div className="page-header">
        <h1>Sleep</h1>
        <p>Eight Sleep nightly scores, stages, and recovery signals</p>
      </div>

      {latest && <LatestNightSummary session={latest} />}

      <div className="filter-bar">
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={30}>Last 30 days</option>
          <option value={60}>Last 60 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div className="card">
        <h2>Sleep Score</h2>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={scoreChartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={12} />
            <YAxis domain={[0, 100]} stroke="var(--text-muted)" />
            <Tooltip
              contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="score"
              stroke="#6366f1"
              strokeWidth={2}
              dot={{ r: 3 }}
              name="Sleep Score"
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="fitness"
              stroke="#22c55e"
              strokeWidth={2}
              dot={{ r: 3 }}
              name="Sleep Fitness"
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h2>Nightly Stages — Last 30 Days</h2>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={stagesChartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={12} />
            <YAxis
              stroke="var(--text-muted)"
              tickFormatter={formatMinutesAxis}
              label={{
                value: "Duration",
                angle: -90,
                position: "insideLeft",
                fill: "var(--text-muted)",
                fontSize: 12,
              }}
            />
            <Tooltip content={<StagesTooltip />} />
            <Legend />
            <Bar dataKey="deep" stackId="stages" fill={STAGE_COLORS.deep} name="Deep" />
            <Bar dataKey="rem" stackId="stages" fill={STAGE_COLORS.rem} name="REM" />
            <Bar dataKey="light" stackId="stages" fill={STAGE_COLORS.light} name="Light" />
            <Bar dataKey="awake" stackId="stages" fill={STAGE_COLORS.awake} name="Awake" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "24px 24px 0 24px" }}>
          <h2>Recent Nights</h2>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Score</th>
              <th>Duration</th>
              <th>Stages (D / R / L / A)</th>
              <th>Avg HR</th>
              <th>HRV</th>
              <th>Latency</th>
              <th>Wake Timeline</th>
            </tr>
          </thead>
          <tbody>
            {recentNights.map((n) => (
              <tr key={n.id} style={{ cursor: "default" }}>
                <td>{formatShortDate(n.date)}</td>
                <td style={{ color: getSleepColor(n.sleep_score), fontWeight: 600 }}>
                  {n.sleep_score != null ? Math.round(n.sleep_score) : "—"}
                </td>
                <td>{formatDurationMinutes(n.total_duration)}</td>
                <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  {formatStages(n)}
                </td>
                <td>{n.avg_hr != null ? `${Math.round(n.avg_hr)} bpm` : "—"}</td>
                <td>{n.hrv != null ? `${Math.round(n.hrv)} ms` : "—"}</td>
                <td>{formatLatency(n.latency)}</td>
                <td style={{ minWidth: 140 }}>
                  {n.wake_events && n.wake_events.length > 0 && n.total_duration ? (
                    <WakeTimeline
                      events={n.wake_events}
                      totalSec={n.total_duration * 60}
                    />
                  ) : (
                    <span style={{ color: "var(--text-muted)", fontSize: 12 }}>—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {recentNights.length === 0 && (
          <div style={{ padding: 24, color: "var(--text-muted)" }}>
            No recent nights found.
          </div>
        )}
      </div>
    </div>
  );
}

function LatestNightSummary({ session }: { session: SleepSession }) {
  return (
    <div className="metric-grid">
      <div className="metric-card">
        <div className="label">Last Sleep Score</div>
        <div className="value" style={{ color: getSleepColor(session.sleep_score) }}>
          {session.sleep_score != null ? Math.round(session.sleep_score) : "—"}
        </div>
        <div className="subtext">{formatShortDate(session.date)}</div>
      </div>
      <div className="metric-card">
        <div className="label">Duration</div>
        <div className="value">{formatDurationMinutes(session.total_duration)}</div>
        <div className="subtext">
          {session.sleep_fitness_score != null
            ? `Fitness: ${Math.round(session.sleep_fitness_score)}`
            : ""}
        </div>
      </div>
      <div className="metric-card">
        <div className="label">Bed / Wake</div>
        <div className="value" style={{ fontSize: 20 }}>
          {formatClock(session.bed_time)} → {formatClock(session.wake_time)}
        </div>
        <div className="subtext">
          {session.latency != null ? `Latency ${formatLatency(session.latency)}` : ""}
        </div>
      </div>
      <div className="metric-card">
        <div className="label">HR / HRV</div>
        <div className="value" style={{ fontSize: 20 }}>
          {session.avg_hr != null ? `${Math.round(session.avg_hr)} bpm` : "—"}
          {" · "}
          {session.hrv != null ? `${Math.round(session.hrv)} ms` : "—"}
        </div>
        <div className="subtext">
          {session.respiratory_rate != null
            ? `Resp: ${session.respiratory_rate.toFixed(1)} /min`
            : ""}
        </div>
      </div>
    </div>
  );
}

function WakeTimeline({ events, totalSec }: { events: WakeEvent[]; totalSec: number }) {
  if (!totalSec || totalSec <= 0) return null;
  return (
    <div
      style={{
        position: "relative",
        height: 10,
        width: "100%",
        background: "var(--bg-hover)",
        borderRadius: 4,
        overflow: "hidden",
      }}
      title={`${events.length} wake event${events.length === 1 ? "" : "s"}`}
    >
      {events.map((e, i) => {
        const leftPct = Math.max(0, Math.min(100, (e.offset_sec / totalSec) * 100));
        const widthPct = Math.max(
          0.5,
          Math.min(100 - leftPct, (e.duration_sec / totalSec) * 100)
        );
        const color = e.type === "out" ? "#ef4444" : "#f59e0b";
        return (
          <div
            key={i}
            title={`${e.type === "out" ? "Out of bed" : "Awake"}: ${formatDurationSeconds(
              e.duration_sec
            )} at +${formatDurationSeconds(e.offset_sec)}`}
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: `${leftPct}%`,
              width: `${widthPct}%`,
              background: color,
            }}
          />
        );
      })}
    </div>
  );
}

function getSleepColor(score?: number | null): string {
  if (score == null) return "var(--text-muted)";
  if (score >= 80) return "var(--green)";
  if (score >= 60) return "var(--orange)";
  return "var(--red)";
}

function formatShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatClock(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDurationMinutes(minutes?: number | null): string {
  if (minutes == null) return "—";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

/**
 * Y-axis tick formatter for the stages chart. Anything >= 60 minutes
 * reads as whole hours (1h, 2h, 3h…); shorter ticks stay in minutes so
 * you can still tell 30m apart from 45m near the bottom of the axis.
 */
function formatMinutesAxis(minutes: number): string {
  if (minutes == null) return "";
  if (minutes >= 60) {
    const h = minutes / 60;
    return Number.isInteger(h) ? `${h}h` : `${h.toFixed(1)}h`;
  }
  return `${Math.round(minutes)}m`;
}

/**
 * Tooltip entry formatter: "1h 23m (28%)" when the stage ran over an
 * hour, "45m (12%)" otherwise. ``total`` is the night's stacked sleep
 * total including Awake time so the four percentages always add up to
 * 100. If the total is zero (shouldn't happen in practice), we skip the
 * percent suffix so we don't render "NaN%".
 */
function formatStageValue(minutes: number, total: number): string {
  if (!minutes || minutes < 0) return "0m";
  const pct = total > 0 ? Math.round((minutes / total) * 100) : null;
  const pctSuffix = pct != null ? ` (${pct}%)` : "";
  if (minutes >= 60) {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes % 60);
    const core = m > 0 ? `${h}h ${m}m` : `${h}h`;
    return `${core}${pctSuffix}`;
  }
  return `${Math.round(minutes)}m${pctSuffix}`;
}

/**
 * Custom Recharts tooltip for the stacked stages chart.
 *
 * Recharts gives us one ``payload`` entry per stacked series (Deep /
 * REM / Light / Awake). We sum all four to compute the night's total,
 * then render each stage as "<duration> (<pct>%)". Total is shown at
 * the bottom so you can see the full night at a glance.
 */
function StagesTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: any[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const total = payload.reduce(
    (sum, p) => sum + (typeof p.value === "number" ? p.value : 0),
    0
  );
  return (
    <div
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "10px 12px",
        fontSize: 13,
        minWidth: 180,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6 }}>{label}</div>
      {payload.map((p) => (
        <div
          key={p.dataKey}
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 12,
            color: p.color,
          }}
        >
          <span>{p.name}</span>
          <span style={{ color: "var(--text)" }}>
            {formatStageValue(p.value || 0, total)}
          </span>
        </div>
      ))}
      <div
        style={{
          marginTop: 6,
          paddingTop: 6,
          borderTop: "1px solid var(--border)",
          display: "flex",
          justifyContent: "space-between",
          color: "var(--text-muted)",
        }}
      >
        <span>Total</span>
        <span style={{ color: "var(--text)" }}>
          {formatDurationMinutes(total)}
        </span>
      </div>
    </div>
  );
}

function formatDurationSeconds(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m <= 0) return `${s}s`;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function formatLatency(latencySec?: number | null): string {
  if (latencySec == null) return "—";
  const m = Math.round(latencySec / 60);
  return `${m}m`;
}

function formatStages(n: SleepSession): string {
  const fmt = (v?: number | null) => (v != null ? `${Math.round(v)}` : "—");
  return `${fmt(n.deep_sleep)} / ${fmt(n.rem_sleep)} / ${fmt(n.light_sleep)} / ${fmt(
    n.awake_time
  )}`;
}
