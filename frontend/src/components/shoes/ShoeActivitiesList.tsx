import { Link } from "react-router-dom";
import { useShoeActivities } from "../../hooks/useShoes";
import { useUnits } from "../../hooks/useUnits";
import { formatShoeDistance } from "../../lib/shoeFormatting";

interface Props {
  shoeId: number;
  pageSize?: number;
  page: number;
  onPageChange: (next: number) => void;
}

/**
 * Paginated tagged-activity list for the shoe detail page. Backend
 * accepts `limit/offset`; we expose Prev/Next over the returned
 * `total`. Page size defaults to 20 (matches History density).
 */
export default function ShoeActivitiesList({
  shoeId,
  pageSize = 20,
  page,
  onPageChange,
}: Props) {
  const { units } = useUnits();
  const offset = page * pageSize;
  const { data, loading, error } = useShoeActivities(shoeId, {
    limit: pageSize,
    offset,
  });

  if (loading) return <div className="loading">Loading activities…</div>;
  if (error) return <div className="error">{error}</div>;

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const hasPrev = page > 0;
  const hasNext = offset + items.length < total;
  const from = total === 0 ? 0 : offset + 1;
  const to = offset + items.length;

  if (total === 0) {
    return (
      <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
        No activities tagged yet. Open a run and pick this shoe from the
        shoe selector.
      </div>
    );
  }

  return (
    <div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Name</th>
            <th>Sport</th>
            <th style={{ textAlign: "right" }}>Distance</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => {
            const href =
              row.source === "apple"
                ? `/activities/${row.id}?source=apple_health`
                : `/activities/${row.id}`;
            return (
              <tr key={`${row.source}:${row.id}`}>
                <td>{formatDate(row.start_date)}</td>
                <td>
                  <Link
                    to={href}
                    style={{ color: "var(--text)", textDecoration: "none" }}
                  >
                    {row.name ?? "Untitled"}
                  </Link>
                </td>
                <td style={{ color: "var(--text-muted)" }}>
                  {row.sport_type ?? "—"}
                </td>
                <td style={{ textAlign: "right" }}>
                  {formatShoeDistance(row.distance_m, units)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "12px 4px 0",
          color: "var(--text-muted)",
          fontSize: 12,
        }}
      >
        <span>
          {from}–{to} of {total}
        </span>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={!hasPrev}
            onClick={() => onPageChange(page - 1)}
          >
            Prev
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={!hasNext}
            onClick={() => onPageChange(page + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString();
}
