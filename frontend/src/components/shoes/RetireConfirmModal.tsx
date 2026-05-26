import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { getErrorMessage } from "../../utils/errors";

interface Props {
  open: boolean;
  shoeName: string;
  onClose: () => void;
  /** Called after the user confirms; resolves once the network request
   *  completes. Errors are caught and surfaced inline. */
  onConfirm: () => Promise<void>;
}

/**
 * "Retire {name}?" confirmation overlay. Explains the soft-delete
 * semantics so the user knows history is preserved.
 */
export default function RetireConfirmModal({
  open,
  shoeName,
  onClose,
  onConfirm,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setBusy(false);
      setError(null);
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`Retire ${shoeName}?`}
      data-testid="retire-confirm-modal"
      onClick={() => {
        if (!busy) onClose();
      }}
    >
      <div
        className="w-full sm:max-w-sm bg-card border border-cardBorder sm:rounded-2xl rounded-t-2xl shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-cardBorder/70">
          <h2 className="text-sm font-semibold text-slate-100">
            Retire {shoeName}?
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="p-1 text-slate-400 hover:text-slate-200 transition-colors disabled:opacity-50"
            aria-label="Close"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="p-4">
          <p style={{ color: "var(--text-muted)", fontSize: 13, margin: 0 }}>
            They&apos;ll be hidden from the active list, but their history
            and tagged activities are preserved. You can unretire them later
            from the Retired filter.
          </p>
          {error && (
            <div className="error" style={{ marginTop: 12 }}>
              {error}
            </div>
          )}
          <div
            style={{
              display: "flex",
              gap: 8,
              justifyContent: "flex-end",
              marginTop: 16,
            }}
          >
            <button
              type="button"
              className="btn btn-ghost"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn"
              onClick={confirm}
              disabled={busy}
            >
              {busy ? "Retiring…" : "Retire"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
