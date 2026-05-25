import { useEffect, useState } from "react";
import { Heart, Loader2, RefreshCw, X } from "lucide-react";
import SourceBadge from "../activity/SourceBadge";
import {
  fetchLinkCandidates,
  linkWorkout,
  type LinkCandidate,
  type LinkSource,
} from "../../api/strength";
import { ApiError } from "../../api/http";
import { formatHmsCompact, distanceWithUnit } from "../activity/utils";
import { useUnits } from "../../hooks/useUnits";

interface Props {
  date: string;
  open: boolean;
  onClose: () => void;
  /** Called once the link succeeds. Parent should reload the session. */
  onLinked: () => void;
}

function formatStartLocal(iso: string): string {
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

function sourceToBadge(source: LinkSource) {
  return source === "strava" ? "strava" : "apple";
}

function isDistanceSport(sport: string): boolean {
  const s = sport.toLowerCase();
  return (
    s.includes("run") ||
    s.includes("ride") ||
    s.includes("walk") ||
    s.includes("hike") ||
    s.includes("bike")
  );
}

export default function LinkWorkoutPicker({
  date,
  open,
  onClose,
  onLinked,
}: Props) {
  const { units } = useUnits();
  const [candidates, setCandidates] = useState<LinkCandidate[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [submittingId, setSubmittingId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setCandidates(null);
      setLoadError(null);
      setActionError(null);
      setSubmittingId(null);
      return;
    }
    void loadCandidates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, date]);

  async function loadCandidates() {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await fetchLinkCandidates(date);
      setCandidates(data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Couldn't load candidates.";
      setLoadError(msg);
      setCandidates([]);
    } finally {
      setLoading(false);
    }
  }

  async function handlePick(candidate: LinkCandidate) {
    const id = `${candidate.source}:${candidate.ref_id}`;
    setSubmittingId(id);
    setActionError(null);
    try {
      await linkWorkout(date, {
        source: candidate.source,
        ref_id: candidate.ref_id,
      });
      onLinked();
      onClose();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          setActionError(
            "This workout is already linked to another session."
          );
        } else if (e.status === 422) {
          setActionError(
            "Workout no longer available — refresh and try again."
          );
        } else if (e.status === 502) {
          // Backend persisted the link with status="no_stream" — the
          // parent will see the degraded panel on reload.
          onLinked();
          onClose();
          return;
        } else {
          setActionError(e.message);
        }
      } else if (e instanceof Error) {
        setActionError(e.message);
      } else {
        setActionError("Couldn't link workout.");
      }
    } finally {
      setSubmittingId(null);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Pick a device workout to link"
      data-testid="link-workout-picker"
    >
      <div className="w-full sm:max-w-md bg-card border border-cardBorder sm:rounded-2xl rounded-t-2xl shadow-xl max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-cardBorder/70">
          <h2 className="text-sm font-semibold text-slate-100">
            Link device workout
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-slate-200 transition-colors"
            aria-label="Close"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <div className="overflow-y-auto flex-1 p-3 space-y-2">
          {loading && (
            <div className="flex items-center gap-2 py-6 justify-center text-xs text-slate-400">
              <Loader2 size={14} className="animate-spin" aria-hidden="true" />
              Loading candidates…
            </div>
          )}

          {!loading && loadError && (
            <div className="py-6 text-center space-y-3">
              <p className="text-xs text-brand-red">{loadError}</p>
              <button
                type="button"
                onClick={() => void loadCandidates()}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium bg-cardBorder text-slate-200 hover:bg-cardBorder/70"
              >
                <RefreshCw size={12} aria-hidden="true" />
                Retry
              </button>
            </div>
          )}

          {!loading &&
            !loadError &&
            candidates != null &&
            candidates.length === 0 && (
              <div
                className="py-8 text-center text-xs text-slate-400"
                data-testid="link-picker-empty"
              >
                No device workouts found within ±1 day of this session.
              </div>
            )}

          {!loading && candidates && candidates.length > 0 && (
            <ul className="space-y-2">
              {candidates.map((c) => {
                const id = `${c.source}:${c.ref_id}`;
                const showDistance =
                  c.distance_m != null && isDistanceSport(c.sport);
                return (
                  <li key={id}>
                    <button
                      type="button"
                      onClick={() => void handlePick(c)}
                      disabled={submittingId != null}
                      className="w-full text-left px-3 py-2.5 rounded-lg border border-cardBorder bg-dashboard/30 hover:bg-cardBorder/30 transition-colors disabled:opacity-50"
                      data-testid={`link-picker-row-${id}`}
                    >
                      <div className="flex items-center gap-1.5 mb-1">
                        <SourceBadge source={sourceToBadge(c.source)} />
                        <span className="text-[10px] uppercase tracking-wider text-slate-500">
                          {c.sport}
                        </span>
                        {submittingId === id && (
                          <Loader2
                            size={12}
                            className="animate-spin text-slate-400 ml-auto"
                            aria-hidden="true"
                          />
                        )}
                      </div>
                      <div className="text-sm font-semibold text-white truncate">
                        {c.name}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
                        <span>{formatStartLocal(c.start_local)}</span>
                        <span>{formatHmsCompact(c.duration_s)}</span>
                        {(c.avg_hr != null || c.max_hr != null) && (
                          <span className="inline-flex items-center gap-1">
                            <Heart
                              size={10}
                              className="text-brand-red"
                              aria-hidden="true"
                            />
                            {c.avg_hr != null ? Math.round(c.avg_hr) : "—"} /{" "}
                            {c.max_hr != null ? Math.round(c.max_hr) : "—"} bpm
                          </span>
                        )}
                        {showDistance && (
                          <span>{distanceWithUnit(c.distance_m, units)}</span>
                        )}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {actionError && (
            <div
              className="px-3 py-2 rounded border border-brand-red/30 bg-brand-red/10 text-[11px] text-brand-red"
              data-testid="link-picker-error"
            >
              {actionError}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
