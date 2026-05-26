/**
 * Typed fetchers for the /api/shoes surface.
 *
 * Mirrors the Pydantic shapes in `backend/routers/shoes.py`
 * (`ShoeOut`, `ShoeDetailOut`, `ShoeCreate`, `ShoePatch`).
 *
 * Distances are always meters on the wire. The frontend converts to
 * km/mi for display via `useUnits` + `lib/shoeFormatting.ts`.
 */
import { fetchJson } from "./http";

export type ShoeStatus = "active" | "retired";
export type ShoeType = "everyday" | "workout" | "race" | "long_run" | "trail";
export type ShoeListFilter = "active" | "retired" | "all";
export type ShoeActivitySource = "strava" | "apple";

export interface Shoe {
  id: number;
  name: string;
  brand: string | null;
  model: string | null;
  shoe_type: ShoeType;
  status: ShoeStatus;
  total_usable_distance_m: number | null;
  purchased_on: string | null; // ISO date (YYYY-MM-DD)
  retired_at: string | null; // ISO datetime
  notes: string | null;
  created_at: string; // ISO datetime
  updated_at: string; // ISO datetime
  cumulative_distance_m: number; // server-computed; 0 when no tagged activities
  percent_used: number | null; // null when total_usable_distance_m is null
}

export interface ShoeDetail extends Shoe {
  tagged_activity_count: number;
}

export interface ShoeCreate {
  name: string; // 1..120
  brand?: string | null; // <= 64
  model?: string | null; // <= 120
  shoe_type?: ShoeType;
  total_usable_distance_m?: number | null; // > 0
  purchased_on?: string | null;
  notes?: string | null;
}

export interface ShoePatch {
  name?: string;
  brand?: string | null;
  model?: string | null;
  shoe_type?: ShoeType;
  total_usable_distance_m?: number | null;
  purchased_on?: string | null;
  notes?: string | null;
  // status is intentionally NOT here. Retire/unretire are verb endpoints.
}

export interface ShoeActivityRow {
  id: number;
  source: ShoeActivitySource;
  name: string | null;
  sport_type: string | null;
  start_date: string | null;
  distance_m: number | null;
}

export interface ShoeActivitiesPage {
  items: ShoeActivityRow[];
  total: number;
}

export function listShoes(filter: ShoeListFilter = "active") {
  const qs = new URLSearchParams({ status: filter }).toString();
  return fetchJson<Shoe[]>(`/shoes?${qs}`);
}

export function getShoe(id: number) {
  return fetchJson<ShoeDetail>(`/shoes/${id}`);
}

export function createShoe(payload: ShoeCreate) {
  return fetchJson<Shoe>("/shoes", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function patchShoe(id: number, payload: ShoePatch) {
  return fetchJson<Shoe>(`/shoes/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function retireShoe(id: number) {
  return fetchJson<Shoe>(`/shoes/${id}/retire`, { method: "POST" });
}

export function unretireShoe(id: number) {
  return fetchJson<Shoe>(`/shoes/${id}/unretire`, { method: "POST" });
}

export function listShoeActivities(
  id: number,
  opts?: { limit?: number; offset?: number },
) {
  const qs = new URLSearchParams();
  if (opts?.limit != null) qs.set("limit", String(opts.limit));
  if (opts?.offset != null) qs.set("offset", String(opts.offset));
  const suffix = qs.toString();
  return fetchJson<ShoeActivitiesPage>(
    `/shoes/${id}/activities${suffix ? `?${suffix}` : ""}`,
  );
}
