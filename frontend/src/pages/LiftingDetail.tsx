import { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useApi } from "../hooks/useApi";
import {
  fetchStrengthSessionOptional,
  resegmentSession,
  unlinkWorkout,
  type ExerciseBreakdown,
  type StrengthSessionDetail,
} from "../api/strength";
import { getErrorMessage } from "../utils/errors";
import { SessionSummaryCard } from "../components/lifting/SessionSummaryCard";
import { ExerciseDetailCard } from "../components/lifting/ExerciseDetailCard";
import { SupersetBracket } from "../components/lifting/SupersetBracket";
import DeviceWorkoutPanel from "../components/strength/DeviceWorkoutPanel";
import LinkWorkoutPicker from "../components/strength/LinkWorkoutPicker";
import SessionHRCurve from "../components/strength/SessionHRCurve";
import { DetailNavArrows } from "../components/ui/DetailNavArrows";
import { useLiftingNeighbors } from "../hooks/useDetailNeighbors";
import { isTypingTarget } from "../utils/dom";

/** A renderable chunk: either a single standalone exercise or a contiguous
 *  superset group of exercises that share a non-null `superset_group_id`. */
type ExerciseGroup =
  | { kind: "single"; exercise: ExerciseBreakdown }
  | { kind: "superset"; groupId: number; exercises: ExerciseBreakdown[] };

/**
 * Walk the (already-ordered) exercises list once and bucket adjacent rows
 * sharing the same non-null `superset_group_id` into a `superset` group.
 * Standalone rows (null or singleton groups) emit as `single`.
 */
function buildExerciseGroups(exercises: ExerciseBreakdown[]): ExerciseGroup[] {
  const groups: ExerciseGroup[] = [];
  let i = 0;
  while (i < exercises.length) {
    const ex = exercises[i];
    const gid = ex.superset_group_id;
    if (gid == null) {
      groups.push({ kind: "single", exercise: ex });
      i += 1;
      continue;
    }
    // Greedily consume adjacent exercises with the same group id.
    const bucket: ExerciseBreakdown[] = [ex];
    let j = i + 1;
    while (j < exercises.length && exercises[j].superset_group_id === gid) {
      bucket.push(exercises[j]);
      j += 1;
    }
    if (bucket.length === 1) {
      // A "group" of one is functionally standalone — render without the
      // bracket so the UI stays uncluttered.
      groups.push({ kind: "single", exercise: bucket[0] });
    } else {
      groups.push({ kind: "superset", groupId: gid, exercises: bucket });
    }
    i = j;
  }
  return groups;
}

function roundsFor(exercises: ExerciseBreakdown[]): number {
  // The number of "rounds" a superset was performed for is the smallest
  // set count across its grouped exercises.
  let min = Number.POSITIVE_INFINITY;
  for (const ex of exercises) {
    const count = ex.sets.length;
    if (count < min) min = count;
  }
  return Number.isFinite(min) ? min : 0;
}

export default function LiftingDetail() {
  const { date } = useParams<{ date: string }>();
  const navigate = useNavigate();
  const dateKey = date ?? "";
  const { data, loading, error } = useApi(
    ["strength", "session", dateKey],
    () => fetchStrengthSessionOptional(dateKey),
    { enabled: Boolean(dateKey) },
  );

  const {
    prevDate,
    nextDate,
    loading: neighborsLoading,
  } = useLiftingNeighbors(dateKey);

  const goPrev = useCallback(() => {
    if (!prevDate) return;
    navigate(`/workouts/lifting/${prevDate}`);
  }, [navigate, prevDate]);
  const goNext = useCallback(() => {
    if (!nextDate) return;
    navigate(`/workouts/lifting/${nextDate}`);
  }, [navigate, nextDate]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      if (e.key === "ArrowLeft" && prevDate) {
        e.preventDefault();
        goPrev();
      } else if (e.key === "ArrowRight" && nextDate) {
        e.preventDefault();
        goNext();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goPrev, goNext, prevDate, nextDate]);

  return (
    <div className="pb-24 pt-2">
      <Header
        onPrev={goPrev}
        onNext={goNext}
        hasPrev={prevDate != null}
        hasNext={nextDate != null}
        neighborsLoading={neighborsLoading}
      />
      {loading ? (
        <LoadingSkeleton />
      ) : error ? (
        <ErrorBanner message={error} />
      ) : data == null ? (
        <EmptyState onBack={() => navigate(-1)} />
      ) : (
        <SessionBody session={data} dateKey={dateKey} />
      )}
    </div>
  );
}

interface HeaderProps {
  onPrev: () => void;
  onNext: () => void;
  hasPrev: boolean;
  hasNext: boolean;
  neighborsLoading: boolean;
}

function Header({
  onPrev,
  onNext,
  hasPrev,
  hasNext,
  neighborsLoading,
}: HeaderProps) {
  const navigate = useNavigate();
  return (
    <div className="px-1 mb-3 sticky top-0 z-20 bg-dashboard/95 backdrop-blur-md pt-1 pb-3 -mx-4 px-4 sm:mx-0 sm:px-0">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate(-1)}
          aria-label="Close"
          className="p-1.5 -ml-1.5 text-slate-400 hover:text-white transition-colors bg-cardBorder/30 rounded-full"
        >
          <X size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-bold text-white tracking-tight">
            Lifting Detail
          </h1>
        </div>
        <DetailNavArrows
          onPrev={onPrev}
          onNext={onNext}
          hasPrev={hasPrev}
          hasNext={hasNext}
          loading={neighborsLoading}
          size={18}
          prevLabel="Previous lifting session"
          nextLabel="Next lifting session"
        />
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      <div className="h-28 rounded-2xl bg-card border border-cardBorder animate-pulse" />
      <div className="h-40 rounded-2xl bg-card border border-cardBorder animate-pulse" />
      <div className="h-40 rounded-2xl bg-card border border-cardBorder animate-pulse" />
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="px-3 py-2 rounded-md bg-brand-red/10 border border-brand-red/40 text-xs text-brand-red"
    >
      {message}
    </div>
  );
}

function EmptyState({ onBack }: { onBack: () => void }) {
  return (
    <div className="text-center py-12 px-4">
      <p className="text-sm text-slate-300 mb-3">
        No strength session on this date.
      </p>
      <button
        type="button"
        onClick={onBack}
        className="text-xs font-medium px-3 py-1.5 rounded-md border border-cardBorder text-slate-300 hover:text-white hover:border-slate-500 transition-colors"
      >
        Back to history
      </button>
    </div>
  );
}

function SessionBody({
  session,
  dateKey,
}: {
  session: StrengthSessionDetail;
  dateKey: string;
}) {
  const queryClient = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);

  const reload = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["strength", "session", dateKey],
    });
  };

  const handleUnlink = async () => {
    setBusy(true);
    setPanelError(null);
    try {
      await unlinkWorkout(dateKey);
      await reload();
    } catch (e) {
      setPanelError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const handleRetry = async () => {
    setBusy(true);
    setPanelError(null);
    try {
      await resegmentSession(dateKey);
      await reload();
    } catch (e) {
      setPanelError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const groups = buildExerciseGroups(session.exercises);
  const showCurve =
    session.hr_curve != null ||
    session.segmentation?.status === "no_curve";

  return (
    <div className="space-y-3">
      <SessionSummaryCard session={session} />
      <DeviceWorkoutPanel
        date={dateKey}
        link={session.link}
        segmentation={session.segmentation}
        onOpenPicker={() => setPickerOpen(true)}
        onUnlink={handleUnlink}
        onRetry={handleRetry}
        busy={busy}
        error={panelError}
      />
      {showCurve && (
        <SessionHRCurve
          hrCurve={session.hr_curve}
          segmentMarkers={session.segment_markers}
          segmentationStatus={session.segmentation?.status ?? null}
        />
      )}
      <div className="space-y-2">
        {groups.map((g, idx) =>
          g.kind === "single" ? (
            <ExerciseDetailCard
              key={`single-${idx}-${g.exercise.name}`}
              exercise={g.exercise}
            />
          ) : (
            <SupersetBracket
              key={`superset-${g.groupId}-${idx}`}
              exerciseCount={g.exercises.length}
              rounds={roundsFor(g.exercises)}
            >
              {g.exercises.map((ex) => (
                <ExerciseDetailCard
                  key={`${g.groupId}-${ex.name}`}
                  exercise={ex}
                />
              ))}
            </SupersetBracket>
          ),
        )}
      </div>
      <LinkWorkoutPicker
        date={dateKey}
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onLinked={() => void reload()}
      />
    </div>
  );
}
