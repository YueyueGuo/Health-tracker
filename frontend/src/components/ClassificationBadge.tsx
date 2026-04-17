import type { ClassificationType } from "../api/client";

interface Props {
  type: ClassificationType;
  flags?: string[] | null;
  compact?: boolean;
}

/**
 * A colored pill representing a workout classification, optionally followed
 * by one or more flag chips (is_long, has_speed_component, etc.).
 *
 * When `compact` is true, flags are rendered as single-character icons to
 * save horizontal space in tables.
 */
export default function ClassificationBadge({ type, flags, compact = false }: Props) {
  if (!type) {
    return <span className="badge badge-unknown">—</span>;
  }
  return (
    <span className="badge-group">
      <span className={`badge badge-${type}`}>{type}</span>
      {flags?.map((f) => (
        <span key={f} className="chip" title={humanizeFlag(f)}>
          {compact ? flagIcon(f) : humanizeFlag(f)}
        </span>
      ))}
    </span>
  );
}

function humanizeFlag(flag: string): string {
  switch (flag) {
    case "is_long":
      return "long";
    case "has_speed_component":
      return "w/ speed";
    case "has_warmup_cooldown":
      return "w/u + c/d";
    case "is_hilly":
      return "hilly";
    default:
      return flag;
  }
}

function flagIcon(flag: string): string {
  switch (flag) {
    case "is_long":
      return "L";
    case "has_speed_component":
      return "⚡";
    case "has_warmup_cooldown":
      return "↕";
    case "is_hilly":
      return "⛰";
    default:
      return "•";
  }
}
