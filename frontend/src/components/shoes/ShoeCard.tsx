import { Link } from "react-router-dom";
import type { Shoe } from "../../api/shoes";
import { useUnits } from "../../hooks/useUnits";
import {
  formatShoeDistance,
  progressTone,
} from "../../lib/shoeFormatting";
import ShoeProgressBar from "./ShoeProgressBar";
import ShoeTypeBadge from "./ShoeTypeBadge";

interface Props {
  shoe: Shoe;
}

/**
 * One-shoe row on the `/shoes` list. Card-styled; clicking the name
 * navigates to the detail page.
 */
export default function ShoeCard({ shoe }: Props) {
  const { units } = useUnits();
  const tone = progressTone(shoe.percent_used);
  const cumulative = formatShoeDistance(shoe.cumulative_distance_m, units);
  const target = formatShoeDistance(shoe.total_usable_distance_m, units);

  const subline =
    [shoe.brand, shoe.model].filter((s): s is string => Boolean(s)).join(" · ") ||
    null;

  const warnChip =
    tone === "danger" ? (
      <span
        className="chip"
        style={{
          background: "rgba(239,68,68,0.15)",
          color: "#ef4444",
          borderColor: "rgba(239,68,68,0.4)",
        }}
        data-testid="overdue-chip"
      >
        Overdue — consider retiring
      </span>
    ) : tone === "warn" ? (
      <span
        className="chip"
        style={{
          background: "rgba(245,158,11,0.15)",
          color: "#f59e0b",
          borderColor: "rgba(245,158,11,0.4)",
        }}
        data-testid="approaching-eol-chip"
      >
        Approaching end of life
      </span>
    ) : null;

  return (
    <div
      className="card"
      style={{ marginBottom: 12, padding: 16 }}
      data-testid="shoe-card"
      data-shoe-id={shoe.id}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Link
              to={`/shoes/${shoe.id}`}
              style={{
                fontWeight: 600,
                fontSize: 15,
                color: "var(--text)",
                textDecoration: "none",
              }}
            >
              {shoe.name}
            </Link>
            <ShoeTypeBadge type={shoe.shoe_type} />
            {shoe.status === "retired" && (
              <span className="chip" data-testid="retired-pill">
                retired
              </span>
            )}
          </div>
          {subline && (
            <div
              style={{
                color: "var(--text-muted)",
                fontSize: 12,
                marginTop: 4,
              }}
            >
              {subline}
            </div>
          )}
        </div>
        {warnChip}
      </div>

      <div style={{ marginTop: 12 }}>
        {shoe.total_usable_distance_m == null ? (
          <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
            {cumulative} logged · no target set
          </div>
        ) : (
          <>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 12,
                color: "var(--text-muted)",
                marginBottom: 6,
              }}
            >
              <span>{cumulative}</span>
              <span>of {target}</span>
            </div>
            <ShoeProgressBar percent={shoe.percent_used} />
          </>
        )}
      </div>
    </div>
  );
}
