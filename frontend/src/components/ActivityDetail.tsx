import { useState } from "react";
import { useParams } from "react-router-dom";
import {
  fetchActivity,
  fetchActivityStreams,
  reclassifyActivity,
  type ActivityDetail,
} from "../api/activities";
import { fetchLatestWorkoutInsight, type WorkoutInsight } from "../api/insights";
import { getActivityWeather } from "../api/weather";
import { useApi } from "../hooks/useApi";
import { classifyActivity } from "../lib/historyEvents";
import { getErrorMessage } from "../utils/errors";
import ActivityDetailRide from "./activity/ActivityDetailRide";
import ActivityDetailRun from "./activity/ActivityDetailRun";
import ActivityDetailStrength from "./activity/ActivityDetailStrength";
import ActivityHeader from "./activity/ActivityHeader";
import WorkoutInsightView from "./activity/WorkoutInsightView";
import LocationPicker from "./LocationPicker";
import RPECard from "./RPECard";

export default function ActivityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const activityId = Number(id);
  const { data: activity, loading, error, reload } = useApi(
    () => fetchActivity(activityId),
    [activityId]
  );
  const { data: weather } = useApi(
    () => getActivityWeather(activityId, { raw: true }),
    [activityId]
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
      setInsight(result.insight);
      setInsightModel(result.model);
    } catch (e) {
      setInsightError(getErrorMessage(e));
    } finally {
      setAnalyzing(false);
    }
  };

  const handleLoadStreams = async () => {
    setStreamsLoading(true);
    setStreamsError(null);
    try {
      const s = await fetchActivityStreams(activityId);
      setStreams(s);
    } catch (e) {
      setStreamsError(getErrorMessage(e));
    } finally {
      setStreamsLoading(false);
    }
  };

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
        <RPECard
          activityId={activityId}
          initialRpe={activity.rpe}
          initialNotes={activity.user_notes}
          ratedAt={activity.rated_at}
          onSaved={reload}
        />
        {activity.start_lat == null && activity.start_lng == null && (
          <LocationPicker
            activityId={activityId}
            currentLocationId={activity.location_id}
            onChange={reload}
          />
        )}
        <WorkoutInsightView
          insight={insight}
          model={insightModel}
          error={insightError}
          analyzing={analyzing}
          onAnalyze={handleAnalyze}
        />
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
