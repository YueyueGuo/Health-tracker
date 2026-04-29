import { fetchJson } from "./http";
import type { RecoveryTrend } from "./dashboard";

export interface RecoveryRecord extends RecoveryTrend {
  id: number;
  source: string;
  skin_temp: number | null;
  calories: number | null;
}

export function fetchRecovery(days = 30, asOf?: string) {
  const qs = new URLSearchParams();
  qs.set("days", String(days));
  if (asOf) qs.set("as_of", asOf);
  return fetchJson<RecoveryRecord[]>(`/recovery?${qs.toString()}`);
}

export function fetchRecoveryTrends(days = 30) {
  return fetchJson<RecoveryTrend[]>(`/recovery/trends?days=${days}`);
}
