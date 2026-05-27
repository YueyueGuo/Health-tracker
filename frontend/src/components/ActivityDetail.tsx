import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  fetchActivity,
  fetchActivityStreams,
  reclassifyActivity,
  type ActivityDetail,
  type ActivitySource,
} from "../api/activities";
import { fetchLatestWorkoutInsight, type WorkoutInsight } from "../api/insights";
import { getActivityWeather } from "../api/weather";
import { useApi } from "../hooks/useApi";
import { useUnits } from "../hooks/useUnits";
import { classifyActivity } from "../lib/historyEvents";
import { getErrorMessage } from "../utils/errors";
import ActivityDetailRide from "./activity/ActivityDetailRide";
import ActivityDetailRun from "./activity/ActivityDetailRun";
import ActivityDetailStrength from "./activity/ActivityDetailStrength";
import ActivityHeader from "./activity/ActivityHeader";
import WorkoutInsightView from "./activity/WorkoutInsightView";
import LocationPicker from "./LocationPicker";
import RPECard from "./RPECard";
import ShoeSelector from "./shoes/ShoeSelector";

export default function ActivityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const activityId = Number(id);
  // `?source=apple_health|strava` disambiguates Apple-Watch HDP ids that
  // collide with `activities.id`. Legacy URLs without the query keep the
  // backend's Strava-first / Apple-fallback behavior.
  const [searchParams] = useSearchParams();
  const sourceParam = searchParams.get("source");
  const source: ActivitySource | null =
    sourceParam === "apple_health" || sourceParam === "strava"
      ? sourceParam
      : null;
  // Splits for Apple Health workouts are re-binned on the backend based on
  // the user's unit preference (mile splits when imperial, km splits when
  // metric). Forward `units` so the splits redraw in the correct system,
  // and include it in the cache key so a toggle from Settings re-fetches.
  const { units } = useUnits();
  const { data: activity, loading, error, reload } = useApi(
    ["activities", "detail", activityId, source, units],
    () => fetchActivity(activityId, source, units),
  );
  // The /activities/{id}/weather endpoint is Strava-only; for Apple Health
  // workouts it always 404s. Wait until the activity payload arrives so we
  // know the source, then skip the call for Apple. Avoids both a wasted RTT
  // and a 404 in the network panel.
  const { data: weather } = useApi(
    ["activities", "weather", activityId, "raw"],
    () => getActivityWeather(activityId, { raw: true }),
    { enabled: activity != null && activity.source !== "apple_health" },
  );

  const [insight, setInsight] = useState<WorkoutInsight | null>(null);
  const [insightModel, setInsightModel] = useState<string | null>(null);
  const [insightError, setInsightError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  const [streams, setStreams] = useState<Record<string, number[]> | null>(null);
  const [streamsLoading, setStreamsLoading] = useState(false);
  const [streamsError, setStreamsError] = useState<string | null>(null);

  const [reclassifying, setReclassifying] = useState(false);

  const handleAnalyze = async () => {
    setAnalyzing(true);
    setInsightError(null);
    try {
      const result = await fetchLatestWorkoutInsight({ activityId });
      if (!result?.insight) {
        setInsightError("No insight available for this activity yet.");
        return;
      }
      setInsight(result.insight);
      setInsightModel(result.model);
    } catch (e) {
      setInsightError(getErrorMessage(e));
    } finally {
      setAnalyzing(false);
    }
  };

  const handleLoadStreams = useCallback(async () => {
    setStreamsLoading(true);
    setStreamsError(null);
    try {
      const s = await fetchActivityStreams(activityId, source);
      setStreams(s);
    } catch (e) {
      setStreamsError(getErrorMessage(e));
    } finally {
      setStreamsLoading(false);
    }
  }, [activityId, source]);

  // Reset stream state whenever the active activity changes so that
  // navigating from one detail page to another doesn't carry the previous
  // workout's HR series (or a stale `streamsError`) into the new page.
  useEffect(() => {
    setStreams(null);
    setStreamsError(null);
    setStreamsLoading(false);
  }, [activityId]);

  // Apple Health streams come pre-cached in the workout `raw_payload`, so
  // there's no network cost — fetch them eagerly once the activity loads.
  useEffect(() => {
    if (
      activity?.source === "apple_health" &&
      streams === null &&
      !streamsLoading &&
      !streamsError
    ) {
      void handleLoadStreams();
    }
  }, [activity?.source, streams, streamsLoading, streamsError, handleLoadStreams]);

  const handleReclassify = async () => {
    setReclassifying(true);
    try {
      await reclassifyActivity(activityId);
      await reload();
    } finally {
      setReclassifying(false);
    }
  };

  if (loading) return <div className="text-sm text-slate-400 p-4">Loading activity…</div>;
  if (error) return <div className="text-sm text-brand-red p-4">{error}</div>;
  if (!activity) return null;

  const SportView = pickSportView(activity);
  // Foot-sport gate for the shoe selector — runs, hikes, walks, and the
  // Other fall-through (treadmill, etc.) all render the Run-style detail
  // view, so any of those should show a shoe row. Rides and strength
  // workouts stay out.
  const isFootSport = SportView === ActivityDetailRun;

  return (
    <div className="pb-24 pt-2">
      <ActivityHeader
        activity={activity}
        reclassifying={reclassifying}
        onReclassify={handleReclassify}
      />
      <SportView
        activity={activity}
        weather={weather}
        streams={streams}
        streamsLoading={streamsLoading}
        streamsError={streamsError}
        onLoadStreams={handleLoadStreams}
      />
      <div className="space-y-3 mt-3">
        {isFootSport && (
          <ShoeSelector
            activityId={activityId}
            source={activity.source ?? null}
            currentShoeId={activity.shoe_id ?? null}
            onChange={reload}
          />
        )}
        {activity.source !== "apple_health" && (
          <RPECard
            activityId={activityId}
            initialRpe={activity.rpe}
            initialNotes={activity.user_notes}
            ratedAt={activity.rated_at}
            onSaved={reload}
          />
        )}
        {activity.source !== "apple_health" &&
          activity.start_lat == null &&
          activity.start_lng == null && (
            <LocationPicker
              activityId={activityId}
              currentLocationId={activity.location_id}
              onChange={reload}
            />
          )}
        {activity.source !== "apple_health" && (
          <WorkoutInsightView
            insight={insight}
            model={insightModel}
            error={insightError}
            analyzing={analyzing}
            onAnalyze={handleAnalyze}
          />
        )}
      </div>
    </div>
  );
}

type SportViewProps = {
  activity: ActivityDetail;
  weather: Awaited<ReturnType<typeof getActivityWeather>>;
  streams: Record<string, number[]> | null;
  streamsLoading: boolean;
  streamsError: string | null;
  onLoadStreams: () => void;
};

function pickSportView(activity: ActivityDetail): React.FC<SportViewProps> {
  const category = classifyActivity(activity.sport_type);
  switch (category) {
    case "Ride":
      return ActivityDetailRide;
    case "Strength":
      return ActivityDetailStrength;
    case "Run":
    case "Hike":
    case "Walk":
    case "Other":
    default:
      return ActivityDetailRun;
  }
}
