import { useCallback, useEffect } from "react";
import { ChevronLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import ClassificationBadge from "../ClassificationBadge";
import SourceBadge from "./SourceBadge";
import type { ActivityDetail, ActivitySource } from "../../api/activities";
import { activitySourceToBadge } from "../../lib/historyEvents";
import { formatActivityDateTime } from "./utils";
import { DetailNavArrows } from "../ui/DetailNavArrows";
import { useActivityNeighbors } from "../../hooks/useDetailNeighbors";
import { isTypingTarget } from "../../utils/dom";

interface Props {
  activity: ActivityDetail;
  reclassifying: boolean;
  onReclassify: () => void;
}

export default function ActivityHeader({
  activity,
  reclassifying,
  onReclassify,
}: Props) {
  const navigate = useNavigate();
  // Apple Health and Strava ids can collide — pin both id+source for neighbor
  // resolution and always include `?source=` in the URL when stepping.
  const currentSource: ActivitySource = activity.source ?? "strava";
  const {
    prev: prevActivity,
    next: nextActivity,
    loading: neighborsLoading,
  } = useActivityNeighbors(activity.id, currentSource);

  const goPrev = useCallback(() => {
    if (!prevActivity) return;
    navigate(`/activities/${prevActivity.id}?source=${prevActivity.source}`);
  }, [navigate, prevActivity]);
  const goNext = useCallback(() => {
    if (!nextActivity) return;
    navigate(`/activities/${nextActivity.id}?source=${nextActivity.source}`);
  }, [navigate, nextActivity]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      if (e.key === "ArrowLeft" && prevActivity) {
        e.preventDefault();
        goPrev();
      } else if (e.key === "ArrowRight" && nextActivity) {
        e.preventDefault();
        goNext();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goPrev, goNext, prevActivity, nextActivity]);

  return (
    <div className="px-1 mb-3 sticky top-0 z-20 bg-dashboard/95 backdrop-blur-md pt-1 pb-3 -mx-4 px-4 sm:mx-0 sm:px-0">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate(-1)}
          aria-label="Go back"
          className="p-1.5 -ml-1.5 text-slate-400 hover:text-white transition-colors bg-cardBorder/30 rounded-full"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <h1 className="text-lg font-bold text-white tracking-tight truncate">
              {activity.name}
            </h1>
            <SourceBadge source={activitySourceToBadge(activity.source)} />
          </div>
          <p className="text-[10px] text-slate-400">
            {formatActivityDateTime(activity.start_date_local)}
          </p>
        </div>
        <DetailNavArrows
          onPrev={goPrev}
          onNext={goNext}
          hasPrev={prevActivity != null}
          hasNext={nextActivity != null}
          loading={neighborsLoading}
          size={18}
          prevLabel="Previous workout"
          nextLabel="Next workout"
        />
      </div>
      <div className="flex items-center flex-wrap gap-2 mt-2 pl-9">
        <ClassificationBadge
          type={activity.classification_type}
          flags={activity.classification_flags}
        />
        {activity.enrichment_status !== "complete" && (
          <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-cardBorder/40 text-slate-400">
            {activity.enrichment_status}
          </span>
        )}
        {activity.classification_type && (
          <button
            type="button"
            onClick={onReclassify}
            disabled={reclassifying}
            className="text-[10px] px-2 py-0.5 rounded border border-cardBorder text-slate-400 hover:text-white hover:border-slate-500 transition-colors disabled:opacity-50"
          >
            {reclassifying ? "Reclassifying…" : "Reclassify"}
          </button>
        )}
      </div>
    </div>
  );
}
