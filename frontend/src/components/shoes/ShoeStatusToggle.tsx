import type { ShoeListFilter } from "../../api/shoes";

interface Props {
  value: ShoeListFilter;
  onChange: (next: ShoeListFilter) => void;
}

/**
 * Two-position segmented control: Active | Retired. Mirrors the
 * History filter pill styling so the toolbar reads consistently.
 */
export default function ShoeStatusToggle({ value, onChange }: Props) {
  return (
    <div
      role="tablist"
      aria-label="Shoe status"
      style={{
        display: "inline-flex",
        gap: 4,
        background: "var(--bg-hover, rgba(255,255,255,0.04))",
        padding: 4,
        borderRadius: 999,
      }}
    >
      {(["active", "retired"] as const).map((opt) => {
        const selected = value === opt;
        return (
          <button
            key={opt}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(opt)}
            className={selected ? "btn" : "btn btn-ghost"}
            style={{
              padding: "6px 14px",
              fontSize: 12,
              fontWeight: 600,
              textTransform: "capitalize",
              background: selected ? "var(--accent)" : "transparent",
              color: selected ? "white" : "var(--text-muted)",
              border: "none",
            }}
          >
            {opt}
          </button>
        );
      })}
    </div>
  );
}
