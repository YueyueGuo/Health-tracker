import type { ShoeType } from "../../api/shoes";

const LABELS: Record<ShoeType, string> = {
  everyday: "Everyday",
  workout: "Workout",
  race: "Race",
  long_run: "Long run",
  trail: "Trail",
};

/**
 * Small inline chip rendering a shoe's `shoe_type`. Same `.chip`
 * styling as the rest of the app — see `globals.css`.
 */
export default function ShoeTypeBadge({ type }: { type: ShoeType }) {
  return <span className="chip">{LABELS[type] ?? type}</span>;
}
