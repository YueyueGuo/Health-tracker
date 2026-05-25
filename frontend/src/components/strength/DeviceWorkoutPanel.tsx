import { Heart, Link2, Loader2, RefreshCw, Unlink } from "lucide-react";
import { useMemo, useState } from "react";
import { Card } from "../ui/Card";
import SourceBadge from "../activity/SourceBadge";
import type {
  StrengthSessionLink,
  StrengthSessionSegmentation,
} from "../../api/strength";
import { formatHmsCompact } from "../activity/utils";

interface Props {
  date: string;
  link: StrengthSessionLink | null;
  segmentation: StrengthSessionSegmentation | null;
  onOpenPicker: () => void;
  onUnlink: () => Promise<void> | void;
  onRetry: () => Promise<void> | void;
  /** Set by the parent while a link/unlink/resegment mutation is in
   *  flight so the panel can spin without owning that state itself. */
  busy?: boolean;
  /** Inline error to surface in the panel (e.g. "Stream fetch failed"). */
  error?: string | null;
}

type PanelState =
  | { kind: "unlinked" }
  | { kind: "loading" }
  | { kind: "ok" }
  | { kind: "degraded"; reason: string };

function pickState(
  link: StrengthSessionLink | null,
  segmentation: StrengthSessionSegmentation | null,
  busy: boolean
): PanelState {
  if (busy && !link) return { kind: "loading" };
  if (!link) return { kind: "unlinked" };
  if (segmentation?.status === "pending") return { kind: "loading" };
  if (segmentation?.status === "no_stream") {
    return {
      kind: "degraded",
      reason:
        link.source === "strava"
          ? "Strava heart-rate stream not available yet."
          : "Heart-rate stream not available.",
    };
  }
  if (segmentation?.status === "no_curve") {
    return {
      kind: "degraded",
      reason: "Apple Health workout has no HR time series.",
    };
  }
  if (segmentation?.status === "flat") {
    return {
      kind: "degraded",
      reason: "Couldn't detect set boundaries from HR.",
    };
  }
  if (segmentation?.status === "error") {
    return {
      kind: "degraded",
      reason: "Couldn't process the heart-rate stream.",
    };
  }
  return { kind: "ok" };
}

function sourceToBadge(source: StrengthSessionLink["source"]) {
  return source === "strava" ? "strava" : "apple";
}

function formatStartTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function DeviceWorkoutPanel({
  link,
  segmentation,
  onOpenPicker,
  onUnlink,
  onRetry,
  busy = false,
  error = null,
}: Props) {
  const state = useMemo(
    () => pickState(link, segmentation, busy),
    [link, segmentation, busy]
  );
  const [unlinking, setUnlinking] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const handleUnlink = async () => {
    setUnlinking(true);
    try {
      await onUnlink();
    } finally {
      setUnlinking(false);
    }
  };

  const handleRetry = async () => {
    setRetrying(true);
    try {
      await onRetry();
    } finally {
      setRetrying(false);
    }
  };

  return (
    <Card className="!p-3" data-testid="device-workout-panel">
      <div className="flex items-center gap-2 mb-3">
        <Heart size={14} className="text-brand-red" />
        <h3 className="text-sm font-semibold text-slate-200">Device workout</h3>
      </div>

      {state.kind === "unlinked" && (
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-slate-400">No device workout linked.</p>
          <button
            type="button"
            onClick={onOpenPicker}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-cardBorder text-slate-200 hover:bg-cardBorder/70 transition-colors"
            data-testid="device-workout-link-btn"
          >
            <Link2 size={12} aria-hidden="true" />
            Link…
          </button>
        </div>
      )}

      {state.kind === "loading" && (
        <div
          className="flex items-center gap-2 text-xs text-slate-400 py-1"
          data-testid="device-workout-loading"
        >
          <Loader2 size={14} className="animate-spin" aria-hidden="true" />
          <span>Loading heart-rate stream…</span>
        </div>
      )}

      {link && (state.kind === "ok" || state.kind === "degraded") && (
        <div className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 mb-0.5">
                <SourceBadge source={sourceToBadge(link.source)} />
                <span className="text-[10px] uppercase tracking-wider text-slate-500">
                  {link.sport ?? "—"}
                </span>
              </div>
              <div className="text-sm font-semibold text-white truncate">
                {link.name ?? "Untitled workout"}
              </div>
              <div className="text-[11px] text-slate-500">
                {formatStartTime(link.start_iso)} · {formatHmsCompact(link.duration_s)}
              </div>
            </div>
            <div className="flex flex-col items-end gap-1 shrink-0">
              <div className="flex items-center gap-1 text-[11px] text-slate-300">
                <Heart size={11} className="text-brand-red" aria-hidden="true" />
                <span>
                  {link.avg_hr != null ? Math.round(link.avg_hr) : "—"} /{" "}
                  {link.max_hr != null ? Math.round(link.max_hr) : "—"}
                </span>
                <span className="text-[9px] text-slate-500 ml-0.5">bpm</span>
              </div>
            </div>
          </div>

          {state.kind === "degraded" && (
            <p
              className="text-[11px] text-brand-amber"
              data-testid="device-workout-degraded"
            >
              {state.reason}
            </p>
          )}

          {error && (
            <p
              className="text-[11px] text-brand-red"
              data-testid="device-workout-error"
            >
              {error}
            </p>
          )}

          <div className="flex items-center gap-1.5 pt-1">
            {state.kind === "degraded" && (
              <button
                type="button"
                onClick={handleRetry}
                disabled={retrying || busy}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium bg-cardBorder text-slate-200 hover:bg-cardBorder/70 transition-colors disabled:opacity-50"
                data-testid="device-workout-retry-btn"
              >
                <RefreshCw
                  size={11}
                  className={retrying ? "animate-spin" : ""}
                  aria-hidden="true"
                />
                Retry
              </button>
            )}
            <button
              type="button"
              onClick={onOpenPicker}
              disabled={busy}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium bg-cardBorder text-slate-200 hover:bg-cardBorder/70 transition-colors disabled:opacity-50"
              data-testid="device-workout-change-btn"
            >
              <Link2 size={11} aria-hidden="true" />
              Change
            </button>
            <button
              type="button"
              onClick={handleUnlink}
              disabled={unlinking || busy}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium bg-cardBorder text-slate-300 hover:bg-cardBorder/70 transition-colors disabled:opacity-50"
              data-testid="device-workout-unlink-btn"
            >
              <Unlink size={11} aria-hidden="true" />
              Unlink
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
