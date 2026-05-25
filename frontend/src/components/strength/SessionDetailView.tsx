import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Dumbbell } from "lucide-react";
import { Card } from "../ui/Card";
import { useApi } from "../../hooks/useApi";
import { useUnits } from "../../hooks/useUnits";
import {
  fetchStrengthSessionOptional,
  resegmentSession,
  unlinkWorkout,
} from "../../api/strength";
import DeviceWorkoutPanel from "./DeviceWorkoutPanel";
import LinkWorkoutPicker from "./LinkWorkoutPicker";
import SessionHRCurve from "./SessionHRCurve";
import ExerciseSetsTable from "./ExerciseSetsTable";
import { getErrorMessage } from "../../utils/errors";

function formatVolume(
  kg: number,
  units: ReturnType<typeof useUnits>["units"]
): string {
  if (units === "imperial") {
    return `${Math.round(kg * 2.20462).toLocaleString()} lb`;
  }
  return `${Math.round(kg).toLocaleString()} kg`;
}

function formatDate(date: string): string {
  const d = new Date(`${date}T12:00:00`);
  if (Number.isNaN(d.getTime())) return date;
  return d.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

export default function SessionDetailView() {
  const { date } = useParams<{ date: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { units } = useUnits();
  const safeDate = date ?? "";

  const session = useApi(
    ["strength", "session-optional", safeDate],
    () =>
      safeDate
        ? fetchStrengthSessionOptional(safeDate)
        : Promise.resolve(null),
    { enabled: Boolean(safeDate) }
  );

  const [pickerOpen, setPickerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);

  const reload = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["strength", "session-optional", safeDate],
    });
  };

  const handleUnlink = async () => {
    if (!safeDate) return;
    setBusy(true);
    setPanelError(null);
    try {
      await unlinkWorkout(safeDate);
      await reload();
    } catch (e) {
      setPanelError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const handleRetry = async () => {
    if (!safeDate) return;
    setBusy(true);
    setPanelError(null);
    try {
      await resegmentSession(safeDate);
      await reload();
    } catch (e) {
      setPanelError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (!safeDate) {
    return (
      <div className="py-6 text-center text-sm text-slate-400">
        No session date specified.
      </div>
    );
  }

  if (session.loading) {
    return (
      <div className="py-6 text-center text-sm text-slate-400">
        Loading strength session…
      </div>
    );
  }

  if (session.error) {
    return (
      <div className="py-6 text-center text-sm text-brand-red">
        {session.error}
      </div>
    );
  }

  if (!session.data) {
    return (
      <div className="py-6 text-center text-sm text-slate-400">
        No strength session logged on {formatDate(safeDate)}.
      </div>
    );
  }

  const detail = session.data;
  const totalVolume = detail.exercises.reduce(
    (acc, ex) => acc + (ex.total_volume ?? 0),
    0
  );
  const totalSets = detail.exercises.reduce(
    (acc, ex) => acc + ex.sets.length,
    0
  );

  return (
    <div className="pb-24 pt-3 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="p-1 text-slate-400 hover:text-slate-200"
          aria-label="Back"
        >
          <ArrowLeft size={18} aria-hidden="true" />
        </button>
        <h1 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
          <Dumbbell size={18} className="text-slate-300" aria-hidden="true" />
          Strength session
        </h1>
      </div>

      <Card className="!p-3" data-testid="strength-session-header">
        <div className="text-xs text-slate-500 mb-1">{formatDate(safeDate)}</div>
        <div className="grid grid-cols-3 gap-3">
          <Metric label="Volume" value={formatVolume(totalVolume, units)} />
          <Metric label="Sets" value={totalSets.toString()} />
          <Metric
            label="Exercises"
            value={detail.exercises.length.toString()}
          />
        </div>
      </Card>

      <DeviceWorkoutPanel
        date={safeDate}
        link={detail.link}
        segmentation={detail.segmentation}
        onOpenPicker={() => setPickerOpen(true)}
        onUnlink={handleUnlink}
        onRetry={handleRetry}
        busy={busy}
        error={panelError}
      />

      <ExerciseSetsTable
        exercises={detail.exercises}
        link={detail.link}
        segmentation={detail.segmentation}
      />

      {(detail.hr_curve || detail.segmentation?.status === "no_curve") && (
        <SessionHRCurve
          hrCurve={detail.hr_curve}
          segmentMarkers={detail.segment_markers}
          segmentationStatus={detail.segmentation?.status ?? null}
        />
      )}

      <LinkWorkoutPicker
        date={safeDate}
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onLinked={() => void reload()}
      />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-0.5">
        {label}
      </div>
      <div className="text-sm font-bold text-white">{value}</div>
    </div>
  );
}
