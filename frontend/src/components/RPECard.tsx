import { useEffect, useState } from "react";
import { patchActivityFeedback } from "../api/feedback";

const RPE_LABELS: Record<number, string> = {
  1: "very light",
  2: "light",
  3: "moderate",
  4: "somewhat hard",
  5: "hard",
  6: "hard",
  7: "very hard",
  8: "very hard",
  9: "extremely hard",
  10: "maximal",
};

interface Props {
  activityId: number;
  initialRpe: number | null;
  initialNotes: string | null;
  ratedAt: string | null;
  onSaved?: () => void;
}

/**
 * User-supplied Rate of Perceived Exertion (Borg CR-10) + free-text notes
 * on a completed workout. Feeds the daily recommendation's recent_rpe
 * snapshot so the LLM can calibrate intensity against perceived effort.
 */
export default function RPECard({
  activityId,
  initialRpe,
  initialNotes,
  ratedAt,
  onSaved,
}: Props) {
  const [rpe, setRpe] = useState<number | null>(initialRpe);
  const [notes, setNotes] = useState<string>(initialNotes ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(ratedAt);

  // Re-sync when the detail reloads with a fresh activity.
  useEffect(() => {
    setRpe(initialRpe);
    setNotes(initialNotes ?? "");
    setLastSavedAt(ratedAt);
  }, [activityId, initialRpe, initialNotes, ratedAt]);

  const dirty = rpe !== initialRpe || (notes || "") !== (initialNotes ?? "");

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const resp = await patchActivityFeedback(activityId, {
        rpe,
        user_notes: notes.trim() ? notes.trim() : null,
      });
      setLastSavedAt(resp.rated_at);
      if (onSaved) onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card" style={{ padding: 20 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <h2 style={{ margin: 0 }}>How did that feel?</h2>
        {lastSavedAt && (
          <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
            Rated {new Date(lastSavedAt).toLocaleString()}
          </span>
        )}
      </div>

      <div style={{ marginBottom: 4, color: "var(--text-muted)", fontSize: 13 }}>
        Rate of perceived exertion (1 = very light, 10 = maximal effort)
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
        {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
          <button
            key={n}
            className={rpe === n ? "btn" : "btn btn-ghost"}
            style={{
              minWidth: 40,
              padding: "6px 10px",
              fontWeight: rpe === n ? 600 : 400,
            }}
            onClick={() => setRpe(rpe === n ? null : n)}
          >
            {n}
          </button>
        ))}
      </div>

      {rpe != null && (
        <div
          style={{
            color: "var(--text-muted)",
            fontSize: 13,
            marginTop: 8,
          }}
        >
          {rpe}/10 — {RPE_LABELS[rpe]}
        </div>
      )}

      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Notes (optional): how you felt, legs, fueling, anything that might not show up in HR/power…"
        rows={3}
        style={{ width: "100%", marginTop: 12, padding: 8, boxSizing: "border-box" }}
      />

      {error && <div className="error" style={{ marginTop: 8 }}>{error}</div>}

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button
          className="btn"
          disabled={!dirty || saving}
          onClick={save}
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {dirty && (
          <button
            className="btn btn-ghost"
            disabled={saving}
            onClick={() => {
              setRpe(initialRpe);
              setNotes(initialNotes ?? "");
            }}
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
