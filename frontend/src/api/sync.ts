import { fetchJson } from "./http";

export interface TriggerSyncResponse {
  status: string;
  synced: Record<string, number | string | Record<string, number>>;
  unconfigured?: string[];
  hint?: string | null;
}

export type SyncStatus = Record<string, unknown>;

export function triggerSync(source = "all") {
  return fetchJson<TriggerSyncResponse>("/sync/trigger", {
    method: "POST",
    body: JSON.stringify({ source }),
  });
}

export function fetchSyncStatus() {
  return fetchJson<SyncStatus>("/sync/status");
}
