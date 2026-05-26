import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { retireShoe, unretireShoe } from "../api/shoes";
import { useShoeDetail, invalidateShoes } from "../hooks/useShoes";
import { useUnits } from "../hooks/useUnits";
import {
  formatPercentUsed,
  formatShoeDistance,
  progressTone,
} from "../lib/shoeFormatting";
import RetireConfirmModal from "../components/shoes/RetireConfirmModal";
import ShoeActivitiesList from "../components/shoes/ShoeActivitiesList";
import ShoeFormModal from "../components/shoes/ShoeFormModal";
import ShoeProgressBar from "../components/shoes/ShoeProgressBar";
import ShoeTypeBadge from "../components/shoes/ShoeTypeBadge";
import { getErrorMessage } from "../utils/errors";

export default function ShoeDetail() {
  const { id } = useParams<{ id: string }>();
  const shoeId = id != null ? Number(id) : null;
  const validId = shoeId != null && !Number.isNaN(shoeId);
  const queryClient = useQueryClient();
  const { units } = useUnits();

  const {
    data: shoe,
    loading,
    error,
  } = useShoeDetail(validId ? shoeId : null);

  const [editOpen, setEditOpen] = useState(false);
  const [retireOpen, setRetireOpen] = useState(false);
  const [page, setPage] = useState(0);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [statusBusy, setStatusBusy] = useState(false);

  if (!validId) {
    return <div className="error">Invalid shoe id.</div>;
  }
  if (loading) return <div className="loading">Loading shoe…</div>;
  if (error) return <div className="error">{error}</div>;
  if (!shoe) return null;

  const tone = progressTone(shoe.percent_used);
  const subline = [shoe.brand, shoe.model]
    .filter((s): s is string => Boolean(s))
    .join(" · ");

  const handleSaved = async () => {
    await invalidateShoes(queryClient);
    setEditOpen(false);
  };

  const handleRetire = async () => {
    try {
      await retireShoe(shoe.id);
      await invalidateShoes(queryClient);
      setRetireOpen(false);
    } catch (e) {
      throw e instanceof Error ? e : new Error(getErrorMessage(e));
    }
  };

  const handleUnretire = async () => {
    setStatusBusy(true);
    setStatusError(null);
    try {
      await unretireShoe(shoe.id);
      await invalidateShoes(queryClient);
    } catch (e) {
      setStatusError(getErrorMessage(e));
    } finally {
      setStatusBusy(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Link
          to="/shoes"
          style={{ fontSize: 13, color: "var(--text-muted)" }}
        >
          ← All shoes
        </Link>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 8,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h1 style={{ margin: 0 }}>{shoe.name}</h1>
            <ShoeTypeBadge type={shoe.shoe_type} />
            <span
              className="chip"
              data-testid="shoe-status-pill"
              style={
                shoe.status === "retired"
                  ? { background: "rgba(148,163,184,0.15)" }
                  : undefined
              }
            >
              {shoe.status}
            </span>
          </div>
          {subline && (
            <div
              style={{
                color: "var(--text-muted)",
                fontSize: 13,
                marginTop: 4,
              }}
            >
              {subline}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setEditOpen(true)}
          >
            Edit
          </button>
          {shoe.status === "active" ? (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setRetireOpen(true)}
            >
              Retire
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={handleUnretire}
              disabled={statusBusy}
            >
              {statusBusy ? "Unretiring…" : "Unretire"}
            </button>
          )}
        </div>
      </div>

      {statusError && <div className="error">{statusError}</div>}

      <div className="metric-grid" style={{ marginTop: 16 }}>
        <div className="metric-card">
          <div className="label">Cumulative</div>
          <div className="value">
            {formatShoeDistance(shoe.cumulative_distance_m, units)}
          </div>
          <div className="subtext">
            {shoe.tagged_activity_count} tagged{" "}
            {shoe.tagged_activity_count === 1 ? "activity" : "activities"}
          </div>
        </div>
        <div className="metric-card">
          <div className="label">Lifespan target</div>
          <div className="value">
            {shoe.total_usable_distance_m == null
              ? "No target"
              : formatShoeDistance(shoe.total_usable_distance_m, units)}
          </div>
        </div>
        <div className="metric-card">
          <div className="label">Used</div>
          <div className="value" data-tone={tone}>
            {formatPercentUsed(shoe.percent_used)}
          </div>
        </div>
      </div>

      <div className="card" style={{ padding: 20 }}>
        <h2 style={{ marginTop: 0 }}>Progress</h2>
        <ShoeProgressBar percent={shoe.percent_used} />
      </div>

      {(shoe.purchased_on || shoe.retired_at || shoe.notes) && (
        <div className="card" style={{ padding: 20 }}>
          <h2 style={{ marginTop: 0 }}>Details</h2>
          {shoe.purchased_on && (
            <div style={{ fontSize: 13, marginBottom: 6 }}>
              <strong>Purchased on:</strong> {shoe.purchased_on}
            </div>
          )}
          {shoe.retired_at && (
            <div style={{ fontSize: 13, marginBottom: 6 }}>
              <strong>Retired on:</strong>{" "}
              {new Date(shoe.retired_at).toLocaleDateString()}
            </div>
          )}
          {shoe.notes && (
            <div
              style={{
                fontSize: 13,
                whiteSpace: "pre-wrap",
                color: "var(--text-muted)",
                marginTop: 6,
              }}
            >
              {shoe.notes}
            </div>
          )}
        </div>
      )}

      <div className="card" style={{ padding: 20 }}>
        <h2 style={{ marginTop: 0 }}>Tagged activities</h2>
        <ShoeActivitiesList
          shoeId={shoe.id}
          page={page}
          onPageChange={setPage}
        />
      </div>

      <ShoeFormModal
        open={editOpen}
        shoe={shoe}
        onClose={() => setEditOpen(false)}
        onSaved={handleSaved}
      />
      <RetireConfirmModal
        open={retireOpen}
        shoeName={shoe.name}
        onClose={() => setRetireOpen(false)}
        onConfirm={handleRetire}
      />
    </div>
  );
}
