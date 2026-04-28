import { fetchJson } from "./http";
import type { RecoveryTrend } from "./dashboard";

interface RecoveryRecord extends RecoveryTrend {
  id: number;
  source: string;
  skin_temp: number | null;
  calories: number | null;
}

export function fetchRecovery(days = 30) {
  return fetchJson<RecoveryRecord[]>(`/recovery?days=${days}`);
}

export function fetchRecoveryTrends(days = 30) {
  return fetchJson<RecoveryTrend[]>(`/recovery/trends?days=${days}`);
}
