import { Link } from "react-router-dom";
import { Link as LinkIcon, Plus } from "lucide-react";
import { Card } from "../ui/Card";
import { fetchSyncStatus, type SyncStatusResponse } from "../../api/sync";
import { useApi } from "../../hooks/useApi";
import { SYNC_STATUS_CARD_STALE_TIME_MS } from "../../lib/queryCache";

type SourceKey = "eight_sleep" | "whoop" | "strava" | "weather";

interface SupportedSourceDefinition {
  key: SourceKey;
  label: string;
  supported: true;
}

interface UnsupportedSourceDefinition {
  key: "garmin" | "apple_health";
  label: string;
  supported: false;
}

type SourceDefinition = SupportedSourceDefinition | UnsupportedSourceDefinition;

interface SourceStatus {
  label: string;
  badgeClassName: string;
  detail: string;
}

const SOURCES: SourceDefinition[] = [
  { key: "eight_sleep", label: "Eight Sleep", supported: true },
  { key: "whoop", label: "WHOOP", supported: true },
  { key: "strava", label: "Strava", supported: true },
  { key: "weather", label: "Weather", supported: true },
  { key: "garmin", label: "Garmin Connect", supported: false },
  { key: "apple_health", label: "Apple Health", supported: false },
];

export default function DataSourcesCard() {
  const { data, loading, error } = useApi(["sync", "status"], fetchSyncStatus, {
    staleTime: SYNC_STATUS_CARD_STALE_TIME_MS,
  });

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-4">
        <LinkIcon size={16} className="text-slate-300" />
        <h3 className="text-sm font-semibold text-slate-200">Data Sources</h3>
      </div>

      <div className="space-y-2">
        {SOURCES.map((source) => {
          const status = getSourceStatus(source, data, loading, error);
          return (
            <div
              key={source.key}
              className="flex items-center justify-between gap-3 p-2 rounded-lg bg-dashboard/30 border border-cardBorder/30"
            >
              <div>
                <div className="text-sm font-medium text-slate-300">
                  {source.label}
                </div>
                <div className="text-[10px] text-slate-500">{status.detail}</div>
              </div>
              <span
                className={`text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded whitespace-nowrap ${status.badgeClassName}`}
              >
                {status.label}
              </span>
            </div>
          );
        })}
      </div>

      <Link
        to="/settings"
        className="w-full mt-3 py-2 border border-dashed border-cardBorder rounded-lg flex items-center justify-center gap-1.5 text-slate-400 hover:text-white hover:border-slate-500 hover:bg-cardBorder/20 transition-all no-underline hover:no-underline"
      >
        <Plus size={14} />
        <span className="font-medium text-xs">Manage sync settings</span>
      </Link>
    </Card>
  );
}

function getSourceStatus(
  source: SourceDefinition,
  data: SyncStatusResponse | null,
  loading: boolean,
  error: string | null
): SourceStatus {
  if (!source.supported) {
    return {
      label: "Coming soon",
      badgeClassName: "text-slate-400 bg-slate-500/10",
      detail: "Not integrated yet",
    };
  }

  if (loading) {
    return {
      label: "Checking",
      badgeClassName: "text-slate-300 bg-slate-500/10",
      detail: "Loading sync status",
    };
  }

  if (error) {
    return {
      label: "Unknown",
      badgeClassName: "text-slate-300 bg-slate-500/10",
      detail: "Could not load sync status",
    };
  }

  const row = getSyncRow(data, source.key);
  const state = readString(row?.status).toLowerCase();
  const rowError = readString(row?.error);

  if (rowError || state.startsWith("error") || state === "failed") {
    return {
      label: "Error",
      badgeClassName: "text-brand-red bg-brand-red/10",
      detail: rowError || "Last sync failed",
    };
  }

  if (["running", "syncing", "in_progress", "started"].includes(state)) {
    return {
      label: "Syncing",
      badgeClassName: "text-brand-amber bg-brand-amber/10",
      detail: "Refresh in progress",
    };
  }

  if (["success", "complete", "completed", "ok"].includes(state)) {
    return {
      label: "Connected",
      badgeClassName: "text-brand-green bg-brand-green/10",
      detail: formatLastSync(row),
    };
  }

  if (state === "never") {
    return {
      label: "Needs setup",
      badgeClassName: "text-brand-amber bg-brand-amber/10",
      detail: "No sync has completed yet",
    };
  }

  return {
    label: "Unknown",
    badgeClassName: "text-slate-300 bg-slate-500/10",
    detail: state ? `Last status: ${state}` : "No status available",
  };
}

function getSyncRow(
  data: SyncStatusResponse | null,
  key: SourceKey
): Record<string, unknown> | null {
  if (!data || typeof data !== "object") return null;
  const row = data[key];
  return row && typeof row === "object" && !Array.isArray(row)
    ? (row as Record<string, unknown>)
    : null;
}

function formatLastSync(row: Record<string, unknown> | null): string {
  const lastSync = readString(row?.last_sync);
  const recordsSynced = readNumber(row?.records_synced);

  const parts = [];
  if (lastSync) {
    const date = new Date(lastSync);
    parts.push(
      Number.isNaN(date.getTime()) ? lastSync : `Last sync ${date.toLocaleString()}`
    );
  } else {
    parts.push("Connected");
  }

  if (recordsSynced != null) {
    parts.push(`${recordsSynced} records`);
  }

  return parts.join(" • ");
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}
