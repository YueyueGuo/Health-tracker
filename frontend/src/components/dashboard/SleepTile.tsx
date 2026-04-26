import type { SleepTodayPayload } from "../../api/dashboard";

interface Props {
  data: SleepTodayPayload;
}

export default function SleepTile({ data }: Props) {
  const score = data.last_night_score;
  const duration = data.last_night_duration_min;

  return (
    <div className="metric-card">
      <div className="label">Last Night Sleep</div>
      <div className="value" style={{ color: scoreColor(score) }}>
        {score != null ? Math.round(score) : "—"}
      </div>
      <div className="subtext">{formatDuration(duration)}</div>
      {(data.last_night_deep_min != null || data.last_night_rem_min != null) && (
        <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)" }}>
          Deep {formatDuration(data.last_night_deep_min)} · REM{" "}
          {formatDuration(data.last_night_rem_min)}
        </div>
      )}
    </div>
  );
}

function scoreColor(score: number | null): string {
  if (score == null) return "var(--text-muted)";
  if (score >= 80) return "var(--green)";
  if (score >= 60) return "var(--orange)";
  return "var(--red)";
}

function formatDuration(minutes: number | null): string {
  if (minutes == null) return "—";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}h ${m}m`;
}
