import { useApi } from "../hooks/useApi";
import { fetchWeeklySummaries, type WeeklySummary } from "../api/summary";
import { formatDistanceShort, useUnits } from "../hooks/useUnits";

interface Props {
  weeks?: number;
}

/**
 * A horizontal strip of weekly training summary cards (newest first).
 *
 * Shows totals, a sport-mix bar, and key flag chips (long run, speed
 * session, etc.). Designed to fit inside Dashboard above the fold.
 */
export default function WeeklySummaryCards({ weeks = 4 }: Props) {
  const { data, loading, error } = useApi(() => fetchWeeklySummaries(weeks), [weeks]);

  if (loading) return <div className="loading">Loading weekly summary...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!data || data.length === 0) return null;

  return (
    <div>
      <h2 style={{ marginBottom: 12, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5, fontSize: 13 }}>
        Recent Weeks
      </h2>
      <div className="week-grid">
        {data.map((w) => (
          <WeekCard key={w.iso_week} week={w} />
        ))}
      </div>
    </div>
  );
}

function WeekCard({ week }: { week: WeeklySummary }) {
  const { units } = useUnits();
  const { totals, by_sport, flags, iso_week } = week;
  const hours = totals.duration_s / 3600;

  const flagChips: { key: string; label: string }[] = [];
  if (flags.has_long_run) {
    flagChips.push({
      key: "long-run",
      label: `long run ${formatDistanceShort(flags.long_run_distance_m, units)}`,
    });
  }
  if (flags.has_speed_session) flagChips.push({ key: "speed", label: "speed session" });
  if (flags.has_tempo) flagChips.push({ key: "tempo", label: "tempo" });
  if (flags.has_race) flagChips.push({ key: "race", label: "race" });
  if (flags.has_long_ride) flagChips.push({ key: "long-ride", label: "long ride" });

  return (
    <div className="week-card">
      <div className="week-label">
        {iso_week} &middot; {formatShortRange(week.week_start, week.week_end)}
      </div>
      <div className="week-totals">
        <div>
          <div className="tot-value">{totals.activity_count}</div>
          <div className="tot-label">Activities</div>
        </div>
        <div>
          <div className="tot-value">
            {units === "imperial"
              ? (totals.distance_m / 1609.344).toFixed(1)
              : (totals.distance_m / 1000).toFixed(1)}
          </div>
          <div className="tot-label">{units === "imperial" ? "mi" : "km"}</div>
        </div>
        <div>
          <div className="tot-value">{hours.toFixed(1)}</div>
          <div className="tot-label">hours</div>
        </div>
        {totals.suffer_score > 0 && (
          <div>
            <div className="tot-value">{totals.suffer_score}</div>
            <div className="tot-label">RE</div>
          </div>
        )}
      </div>
      <SportMixBar by_sport={by_sport} />
      {flagChips.length > 0 && (
        <div className="badge-group" style={{ marginTop: 4 }}>
          {flagChips.map((c) => (
            <span key={c.key} className="chip">
              {c.label}
            </span>
          ))}
        </div>
      )}
      {(week.enrichment_pending > 0 || week.classification_pending > 0) && (
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {week.enrichment_pending > 0 && `${week.enrichment_pending} pending enrichment`}
          {week.enrichment_pending > 0 && week.classification_pending > 0 && " · "}
          {week.classification_pending > 0 && `${week.classification_pending} pending classify`}
        </div>
      )}
    </div>
  );
}

function SportMixBar({ by_sport }: { by_sport: WeeklySummary["by_sport"] }) {
  const entries = Object.entries(by_sport);
  if (entries.length === 0) {
    return <div className="sport-mix" style={{ opacity: 0.3 }}><span className="mix-other" /></div>;
  }
  const totalSeconds = entries.reduce((s, [, v]) => s + (v.duration_s || 0), 0);
  if (totalSeconds === 0) {
    // Strength training has 0 duration? fall back to count-weighted mix.
    const totalCount = entries.reduce((s, [, v]) => s + v.count, 0);
    return (
      <div className="sport-mix">
        {entries.map(([sport, v]) => (
          <span
            key={sport}
            className={`mix-${sport.toLowerCase()} ${sportClassFallback(sport)}`}
            style={{ ["--flex" as any]: v.count / totalCount }}
            title={`${sport}: ${v.count} session${v.count !== 1 ? "s" : ""}`}
          />
        ))}
      </div>
    );
  }
  return (
    <div className="sport-mix">
      {entries.map(([sport, v]) => (
        <span
          key={sport}
          className={`mix-${sport.toLowerCase()} ${sportClassFallback(sport)}`}
          style={{ ["--flex" as any]: v.duration_s / totalSeconds }}
          title={`${sport}: ${formatDurationShort(v.duration_s)}`}
        />
      ))}
    </div>
  );
}

function sportClassFallback(sport: string): string {
  const known = ["run", "ride", "weighttraining"];
  return known.includes(sport.toLowerCase()) ? "" : "mix-other";
}

function formatShortRange(start: string, end: string): string {
  const s = new Date(start);
  const e = new Date(end);
  const fmt = (d: Date) =>
    d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return `${fmt(s)} – ${fmt(e)}`;
}

function formatDurationShort(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}
