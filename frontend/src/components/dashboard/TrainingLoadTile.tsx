import { ACWR_TOOLTIP, type TrainingTodayPayload } from "../../api/dashboard";

interface Props {
  data: TrainingTodayPayload;
}

const BAND_COLOR: Record<NonNullable<TrainingTodayPayload["acwr_band"]>, string> = {
  optimal: "var(--green)",
  caution: "var(--orange)",
  elevated: "var(--red)",
  detraining: "var(--text-muted)",
};

export default function TrainingLoadTile({ data }: Props) {
  const { acwr, acwr_band, week_to_date_load, yesterday_stress, days_since_hard } = data;

  return (
    <div className="metric-card">
      <div
        className="label"
        style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
      >
        <span>Training Load</span>
        {acwr_band && acwr != null && (
          <span
            title={ACWR_TOOLTIP}
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 8px",
              borderRadius: 999,
              background: BAND_COLOR[acwr_band],
              color: "#fff",
              letterSpacing: 0.4,
              textTransform: "uppercase",
            }}
          >
            ACWR {acwr.toFixed(2)} · {acwr_band}
          </span>
        )}
      </div>
      <div className="value">{Math.round(week_to_date_load)}</div>
      <div className="subtext">
        WTD load · yesterday {Math.round(yesterday_stress)}
        {days_since_hard != null && (
          <span> · {days_since_hard}d since hard</span>
        )}
      </div>
    </div>
  );
}
