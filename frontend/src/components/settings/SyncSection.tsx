import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Card } from "../ui/Card";
import { useApi } from "../../hooks/useApi";
import {
  invalidateAppDataQueries,
  SYNC_DEBUG_STALE_TIME_MS,
} from "../../lib/queryCache";
import {
  fetchDebugDb,
  fetchSyncStatus,
  triggerSync,
  type SyncSource,
} from "../../api/sync";

function formatMaybeIso(iso: unknown): string {
  if (typeof iso !== "string" || iso.length === 0) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export default function SyncSection() {
  const queryClient = useQueryClient();
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [triggering, setTriggering] = useState<SyncSource | null>(null);
  const [triggerResult, setTriggerResult] = useState<string | null>(null);

  const {
    data: dbInfo,
    loading: dbLoading,
    error: dbError,
  } = useApi(["sync", "debug-db", refreshNonce], () => fetchDebugDb(), {
    staleTime: SYNC_DEBUG_STALE_TIME_MS,
  });

  const {
    data: status,
    loading: statusLoading,
    error: statusError,
  } = useApi(["sync", "status", refreshNonce], () => fetchSyncStatus(), {
    staleTime: SYNC_DEBUG_STALE_TIME_MS,
  });

  const lastSyncSummary = useMemo(() => {
    if (!status || typeof status !== "object") return null;
    const s = status as Record<string, any>;
    const sources = ["strava", "eight_sleep", "whoop", "weather"] as const;
    return sources.map((src) => {
      const row = s[src] ?? {};
      return {
        source: src,
        state: typeof row.status === "string" ? row.status : "unknown",
        lastSync: formatMaybeIso(row.last_sync),
        error: typeof row.error === "string" && row.error.length ? row.error : null,
      };
    });
  }, [status]);

  async function onTrigger(source: SyncSource) {
    setTriggering(source);
    setTriggerResult(null);
    try {
      const res = await triggerSync(source);
      if (res?.error) {
        setTriggerResult(res.error);
      } else {
        const unconfigured = res?.unconfigured?.length
          ? ` (unconfigured: ${res.unconfigured.join(", ")})`
          : "";
        setTriggerResult(`Triggered ${source}${unconfigured}`);
        void invalidateAppDataQueries(queryClient);
      }
      // Re-fetch status + DB info shortly after.
      setTimeout(() => setRefreshNonce((n) => n + 1), 800);
    } catch (e) {
      setTriggerResult(e instanceof Error ? e.message : String(e));
    } finally {
      setTriggering(null);
    }
  }

  return (
    <Card className="p-4 mt-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Data sync</h3>
          <p className="text-xs text-slate-500 mt-1">
            Confirm which SQLite file the backend is using and manually trigger a refresh.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setRefreshNonce((n) => n + 1)}
          className="text-xs bg-card border border-cardBorder rounded-lg px-3 py-2 text-slate-200 hover:bg-cardBorder/20"
        >
          Refresh status
        </button>
      </div>

      <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="rounded-lg border border-cardBorder/40 p-3 bg-cardBorder/10">
          <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
            Database
          </div>
          {dbLoading ? (
            <div className="text-xs text-slate-400 mt-2">Loading…</div>
          ) : dbError ? (
            <div className="text-xs text-brand-red mt-2">{dbError}</div>
          ) : (
            <div className="mt-2 space-y-2">
              <div>
                <div className="text-[10px] text-slate-500">DATABASE_URL</div>
                <div className="text-xs text-slate-200 break-all">
                  {dbInfo?.database_url ?? "—"}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-slate-500">SQLite file (main)</div>
                <div className="text-xs text-slate-200 break-all">
                  {dbInfo?.sqlite_main_file ?? "—"}
                </div>
              </div>
              <div>
                <div className="text-[10px] text-slate-500">Row counts</div>
                <div className="text-xs text-slate-200">
                  {dbInfo?.row_counts
                    ? Object.entries(dbInfo.row_counts)
                        .map(([k, v]) => `${k}: ${v ?? "—"}`)
                        .join(" • ")
                    : "—"}
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-cardBorder/40 p-3 bg-cardBorder/10">
          <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
            Sync status
          </div>
          {statusLoading ? (
            <div className="text-xs text-slate-400 mt-2">Loading…</div>
          ) : statusError ? (
            <div className="text-xs text-brand-red mt-2">{statusError}</div>
          ) : (
            <div className="mt-2 space-y-2">
              {lastSyncSummary?.map((row) => (
                <div key={row.source} className="flex items-start justify-between gap-3">
                  <div className="text-xs text-slate-200 font-semibold">
                    {row.source}
                    <span className="text-[10px] text-slate-500 font-normal ml-2">
                      {row.state}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400 text-right">
                    {row.lastSync}
                  </div>
                </div>
              ))}
              {lastSyncSummary?.some((r) => r.error) && (
                <div className="text-[11px] text-amber-300/90 mt-2">
                  {lastSyncSummary
                    ?.filter((r) => r.error)
                    .map((r) => `${r.source}: ${r.error}`)
                    .join(" • ")}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {(["all", "strava", "eight_sleep", "whoop", "weather"] as SyncSource[]).map(
          (src) => (
            <button
              key={src}
              type="button"
              onClick={() => onTrigger(src)}
              disabled={triggering != null}
              className="text-xs bg-card border border-cardBorder rounded-lg px-3 py-2 text-slate-200 hover:bg-cardBorder/20 disabled:opacity-60"
            >
              {triggering === src ? "Triggering…" : `Sync ${src}`}
            </button>
          )
        )}
      </div>

      {triggerResult && (
        <div className="mt-3 text-xs text-slate-300">{triggerResult}</div>
      )}
    </Card>
  );
}

