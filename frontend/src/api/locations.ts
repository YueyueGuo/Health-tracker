/**
 * Typed fetchers for the /api/locations surface.
 *
 * The design matches the backend router: list / search (via Open-Meteo
 * geocoding) / create / patch / delete / set-default, plus the
 * activity-attach endpoints mounted under /api/activities/{id}/location.
 */

const BASE_URL = "/api";

async function fetchJson<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = "";
    try {
      const body = await resp.json();
      if (body && typeof body === "object" && "detail" in body) {
        detail = String((body as { detail?: unknown }).detail ?? "");
      }
    } catch {
      // not JSON
    }
    throw new Error(
      detail || `API error: ${resp.status} ${resp.statusText}`
    );
  }
  // 204 No Content
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export interface Location {
  id: number;
  name: string;
  lat: number;
  lng: number;
  elevation_m: number | null;
  is_default: boolean;
}

export interface LocationSearchHit {
  name: string | null;
  lat: number;
  lng: number;
  elevation_m: number | null;
  country: string | null;
  admin1: string | null;
  admin2: string | null;
  population: number | null;
}

export interface CreateLocationPayload {
  name: string;
  lat?: number;
  lng?: number;
  elevation_m?: number | null;
  from_activity_id?: number;
  is_default?: boolean;
}

export interface PatchLocationPayload {
  name?: string;
  lat?: number;
  lng?: number;
  elevation_m?: number | null;
  is_default?: boolean;
}

export function listLocations() {
  return fetchJson<Location[]>("/locations");
}

export function searchLocations(q: string, count = 5) {
  const qs = new URLSearchParams({ q, count: String(count) });
  return fetchJson<LocationSearchHit[]>(`/locations/search?${qs}`);
}

export function createLocation(payload: CreateLocationPayload) {
  return fetchJson<Location>("/locations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function patchLocation(id: number, payload: PatchLocationPayload) {
  return fetchJson<Location>(`/locations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteLocation(id: number) {
  return fetchJson<void>(`/locations/${id}`, { method: "DELETE" });
}

export function setDefaultLocation(id: number) {
  return fetchJson<Location>(`/locations/${id}/set-default`, {
    method: "POST",
  });
}

export function attachLocationToActivity(activityId: number, locationId: number) {
  return fetchJson<{
    activity_id: number;
    location_id: number;
    base_elevation_m: number | null;
  }>(`/activities/${activityId}/location`, {
    method: "POST",
    body: JSON.stringify({ location_id: locationId }),
  });
}

export function detachLocationFromActivity(activityId: number) {
  return fetchJson<void>(`/activities/${activityId}/location`, {
    method: "DELETE",
  });
}
