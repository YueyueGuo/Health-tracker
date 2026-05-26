import { formatPercentUsed, progressTone, type ProgressTone } from "../../lib/shoeFormatting";

const TONE_COLORS: Record<ProgressTone, string> = {
  ok: "var(--accent, #22c55e)",
  warn: "#f59e0b", // amber-500
  danger: "#ef4444", // red-500
};

interface Props {
  /** Percent used, server-computed. Null → "no target set" placeholder. */
  percent: number | null | undefined;
  /** When true, suppresses the percent text label on the right (e.g. cards). */
  compact?: boolean;
  /** Optional ARIA label override. */
  ariaLabel?: string;
}

/**
 * Visual mileage progress bar with a three-tone color band:
 * green (`<80%`), amber (`>=80%`), red (`>=100%`).
 *
 * When `percent` is null the bar collapses to a placeholder line so
 * shoes without a configured lifespan still render gracefully.
 */
export default function ShoeProgressBar({ percent, compact, ariaLabel }: Props) {
  if (percent == null) {
    return (
      <div
        style={{ color: "var(--text-muted)", fontSize: 12 }}
        data-testid="shoe-progress-no-target"
      >
        No target set
      </div>
    );
  }

  const tone = progressTone(percent);
  // Cap the fill bar at 100 for the visual width, but the chip + text
  // still show the true percentage so users see "120%" on overdue pairs.
  const fill = Math.min(100, Math.max(0, percent));

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
      }}
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={ariaLabel ?? `Lifespan ${formatPercentUsed(percent)}`}
      data-testid="shoe-progress"
      data-tone={tone}
    >
      <div
        style={{
          flex: 1,
          height: 8,
          background: "var(--bg-hover, rgba(255,255,255,0.06))",
          borderRadius: 999,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${fill}%`,
            height: "100%",
            background: TONE_COLORS[tone],
            transition: "width 240ms ease",
          }}
        />
      </div>
      {!compact && (
        <span
          style={{
            fontSize: 12,
            color: "var(--text-muted)",
            minWidth: 40,
            textAlign: "right",
          }}
        >
          {formatPercentUsed(percent)}
        </span>
      )}
    </div>
  );
}
