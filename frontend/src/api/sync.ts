import { fetchJson } from "./http";

export type SyncSource = "all" | "strava" | "eight_sleep" | "whoop" | "weather";

export type SyncTriggerResponse = {
  status?: "success";
  synced?: Record<string, unknown>;
  unconfigured?: string[];
  hint?: string | null;
  error?: string;
};

export type SyncStatusResponse = Record<string, unknown>;

export type DebugDbResponse = {
  database_url: string;
  sqlite_main_file: string | null;
  database_list: Array<{ seq: number; name: string; file: string }>;
  row_counts: Record<string, number | null>;
};

export function fetchSyncStatus(): Promise<SyncStatusResponse> {
  return fetchJson<SyncStatusResponse>("/sync/status");
}

export function fetchDebugDb(): Promise<DebugDbResponse> {
  return fetchJson<DebugDbResponse>("/sync/debug/db");
}

export function triggerSync(source: SyncSource = "all"): Promise<SyncTriggerResponse> {
  return fetchJson<SyncTriggerResponse>("/sync/trigger", {
    method: "POST",
    body: JSON.stringify({ source }),
  });
}

