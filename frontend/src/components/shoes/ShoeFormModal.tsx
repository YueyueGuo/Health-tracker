import { useEffect } from "react";
import { X } from "lucide-react";
import ShoeForm from "./ShoeForm";
import type { Shoe } from "../../api/shoes";

interface Props {
  open: boolean;
  /** Pass an existing shoe to switch to edit mode. */
  shoe?: Shoe | null;
  onClose: () => void;
  onSaved: (shoe: Shoe) => void | Promise<void>;
}

/**
 * Overlay shell that wraps `ShoeForm` for create + edit flows. Matches
 * the LinkWorkoutPicker dialog idiom: fixed full-screen overlay with a
 * centered card on desktop, sheet-style on mobile.
 */
export default function ShoeFormModal({ open, shoe, onClose, onSaved }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const title = shoe ? "Edit shoe" : "Add a shoe";

  return (
    <div
      // On mobile the sheet is bottom-anchored; pad the bottom by the
      // fixed BottomNav height (h-16 = 4rem) plus the safe-area inset so
      // the card — and its Save button — sit clear of the nav instead of
      // disappearing behind it. Desktop centers the card, so no inset.
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm pb-[calc(4rem+env(safe-area-inset-bottom))] sm:pb-0"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid="shoe-form-modal"
      onClick={onClose}
    >
      <div
        // Cap the height to the space left above the nav so a tall form
        // scrolls internally rather than overflowing under the nav.
        className="w-full sm:max-w-md bg-card border border-cardBorder sm:rounded-2xl rounded-t-2xl shadow-xl max-h-[calc(100vh-5rem)] sm:max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-cardBorder/70">
          <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-slate-200 transition-colors"
            aria-label="Close"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className="overflow-y-auto p-4">
          <ShoeForm shoe={shoe ?? null} onCancel={onClose} onSaved={onSaved} />
        </div>
      </div>
    </div>
  );
}
