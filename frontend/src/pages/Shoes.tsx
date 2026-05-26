import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Shoe, ShoeListFilter } from "../api/shoes";
import { useShoesList, invalidateShoes } from "../hooks/useShoes";
import ShoeCard from "../components/shoes/ShoeCard";
import ShoeFormModal from "../components/shoes/ShoeFormModal";
import ShoeStatusToggle from "../components/shoes/ShoeStatusToggle";

/**
 * `/shoes` list page. Default-active filter; retired toggle; per-card
 * progress bar; "Add shoe" CTA in the toolbar + an "Add your first
 * shoe" CTA in the empty state.
 */
export default function Shoes() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ShoeListFilter>("active");
  const { data, loading, error } = useShoesList(filter);
  const [formOpen, setFormOpen] = useState(false);

  // Retired list: backend orders by `created_at desc`. Per the plan
  // open-question 6, sort by `retired_at desc` client-side so
  // most-recently-retired comes first.
  const sorted = useMemo<Shoe[]>(() => {
    const rows = data ?? [];
    if (filter !== "retired") return rows;
    return [...rows].sort((a, b) => {
      const aT = a.retired_at ? new Date(a.retired_at).getTime() : 0;
      const bT = b.retired_at ? new Date(b.retired_at).getTime() : 0;
      return bT - aT;
    });
  }, [data, filter]);

  const handleSaved = async () => {
    await invalidateShoes(queryClient);
    setFormOpen(false);
  };

  return (
    <div>
      <div className="page-header">
        <h1>Running shoes</h1>
        <p>Tag a shoe on a run to track its mileage.</p>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <ShoeStatusToggle value={filter} onChange={setFilter} />
        <button
          type="button"
          className="btn"
          onClick={() => setFormOpen(true)}
          data-testid="add-shoe-button"
        >
          Add shoe
        </button>
      </div>

      {loading && <div className="loading">Loading shoes…</div>}
      {error && <div className="error">{error}</div>}

      {!loading && !error && sorted.length === 0 && filter === "active" && (
        <div className="card" style={{ padding: 32, textAlign: "center" }}>
          <h2 style={{ marginTop: 0 }}>No shoes yet</h2>
          <p style={{ color: "var(--text-muted)" }}>
            Track each pair so you know when to replace them.
          </p>
          <button
            type="button"
            className="btn"
            onClick={() => setFormOpen(true)}
            data-testid="add-first-shoe"
          >
            Add your first shoe
          </button>
        </div>
      )}

      {!loading && !error && sorted.length === 0 && filter === "retired" && (
        <div style={{ color: "var(--text-muted)", padding: 12 }}>
          Nothing retired yet.
        </div>
      )}

      {!loading && !error && sorted.length > 0 && (
        <div>
          {sorted.map((shoe) => (
            <ShoeCard key={shoe.id} shoe={shoe} />
          ))}
        </div>
      )}

      <ShoeFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSaved={handleSaved}
      />
    </div>
  );
}
