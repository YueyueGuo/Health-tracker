import { Link } from "react-router-dom";
import { useShoesList } from "../../hooks/useShoes";
import { formatPercentUsed } from "../../lib/shoeFormatting";

/**
 * Entry-point card on the Settings page. Mounted between
 * `<GoalsSection />` and `<SyncSection />`. Renders a one-line live
 * summary ("3 active · Vaporfly 3 at 78%") and a "Manage shoes" CTA
 * → `/shoes`.
 */
export default function ShoesSettingsCard() {
  const { data: shoes, loading } = useShoesList("active");

  const count = shoes?.length ?? 0;
  const highest = pickHighestPercent(shoes ?? []);

  let summary: string;
  if (loading) summary = "Loading…";
  else if (count === 0) summary = "No shoes yet";
  else if (highest)
    summary = `${count} active · ${highest.name} at ${formatPercentUsed(
      highest.percent_used,
    )}`;
  else summary = `${count} active`;

  return (
    <div
      className="card"
      style={{ padding: 20, marginBottom: 16 }}
      data-testid="shoes-settings-card"
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h2 style={{ marginTop: 0, marginBottom: 4 }}>Running shoes</h2>
          <p
            style={{
              color: "var(--text-muted)",
              margin: 0,
              fontSize: 13,
            }}
          >
            Track mileage on each pair, retire old ones, tag them on runs.
          </p>
          <div
            style={{
              color: "var(--text-muted)",
              fontSize: 12,
              marginTop: 8,
            }}
          >
            {summary}
          </div>
        </div>
        <Link to="/shoes" className="btn" style={{ whiteSpace: "nowrap" }}>
          Manage shoes
        </Link>
      </div>
    </div>
  );
}

function pickHighestPercent(shoes: { name: string; percent_used: number | null }[]) {
  let best: { name: string; percent_used: number } | null = null;
  for (const s of shoes) {
    if (s.percent_used == null) continue;
    if (best == null || s.percent_used > best.percent_used) {
      best = { name: s.name, percent_used: s.percent_used };
    }
  }
  return best;
}
