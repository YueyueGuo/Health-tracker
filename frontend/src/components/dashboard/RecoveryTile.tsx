import type { RecoveryTodayPayload } from "../../api/dashboard";

interface Props {
  data: RecoveryTodayPayload;
}

const SOURCE_LABEL: Record<NonNullable<RecoveryTodayPayload["hrv_source"]>, string> = {
  eight_sleep: "Eight Sleep",
  whoop: "Whoop",
};

export default function RecoveryTile({ data }: Props) {
  const hrv = data.today_hrv;
  const rhr = data.today_resting_hr;
  const trend = data.hrv_trend;
  const baseline = data.hrv_baseline_7d;

  return (
    <div className="metric-card">
      <div
        className="label"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
      >
        <span>Recovery</span>
        {data.hrv_source && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              padding: "2px 6px",
              borderRadius: 999,
              background: "var(--bg)",
              border: "1px solid var(--border)",
              color: "var(--text-muted)",
              letterSpacing: 0.3,
              textTransform: "none",
            }}
          >
            {SOURCE_LABEL[data.hrv_source]}
          </span>
        )}
      </div>
      <div className="value" style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span>{hrv != null ? Math.round(hrv) : "—"}</span>
        <span style={{ fontSize: 14, color: "var(--text-muted)", fontWeight: 500 }}>ms HRV</span>
        {trend && (
          <span
            aria-label={`HRV trend ${trend}`}
            style={{ fontSize: 18, color: trendColor(trend), fontWeight: 700 }}
          >
            {trendArrow(trend)}
          </span>
        )}
      </div>
      <div className="subtext">
        {rhr != null ? `${Math.round(rhr)} bpm RHR` : "RHR —"}
        {baseline != null && (
          <span> · 7d avg {Math.round(baseline)} ms</span>
        )}
      </div>
    </div>
  );
}

function trendArrow(trend: NonNullable<RecoveryTodayPayload["hrv_trend"]>): string {
  if (trend === "up") return "↑";
  if (trend === "down") return "↓";
  return "→";
}

function trendColor(trend: NonNullable<RecoveryTodayPayload["hrv_trend"]>): string {
  if (trend === "up") return "var(--green)";
  if (trend === "down") return "var(--red)";
  return "var(--text-muted)";
}
