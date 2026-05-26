import { ChevronLeft, ChevronRight } from "lucide-react";

export interface DetailNavArrowsProps {
  onPrev: () => void;
  onNext: () => void;
  hasPrev: boolean;
  hasNext: boolean;
  loading?: boolean;
  /** Icon size, in px. Detail headers vary: `SleepRecoveryDetailsCard` pairs
   *  with its 24px back chevron; Activity / Lifting headers pair with 18px. */
  size?: number;
  /** Optional aria-label overrides for screen readers. */
  prevLabel?: string;
  nextLabel?: string;
}

/**
 * Pair of prev/next chevron buttons used on detail pages. Styling mirrors the
 * home-page `dashboard/Header.tsx` chevrons (slate-400 idle, hover white,
 * disabled drops to opacity 30 with no hover affordance). Buttons render
 * disabled (greyed) when the corresponding neighbor is missing OR while
 * neighbors are still being computed.
 */
export function DetailNavArrows({
  onPrev,
  onNext,
  hasPrev,
  hasNext,
  loading = false,
  size = 18,
  prevLabel = "Previous",
  nextLabel = "Next",
}: DetailNavArrowsProps) {
  const prevDisabled = loading || !hasPrev;
  const nextDisabled = loading || !hasNext;
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        className="p-2 text-slate-400 hover:text-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-slate-400"
        aria-label={prevLabel}
        aria-disabled={prevDisabled}
        disabled={prevDisabled}
        onClick={onPrev}
      >
        <ChevronLeft size={size} />
      </button>
      <button
        type="button"
        className="p-2 text-slate-400 hover:text-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-slate-400"
        aria-label={nextLabel}
        aria-disabled={nextDisabled}
        disabled={nextDisabled}
        onClick={onNext}
      >
        <ChevronRight size={size} />
      </button>
    </div>
  );
}

export default DetailNavArrows;
