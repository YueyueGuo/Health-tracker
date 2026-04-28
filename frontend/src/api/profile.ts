/**
 * Persisted profile preferences (camelCase payload matches backend /api/profile).
 */

import { fetchJson } from "./http";
import type { ProfilePreferences } from "../hooks/useProfilePreferences";

export function fetchProfile(): Promise<ProfilePreferences> {
  return fetchJson<ProfilePreferences>("/profile");
}

/** Merge partial PATCH; send full merged document after GET for simplicity. */
export function patchProfile(prefs: ProfilePreferences): Promise<ProfilePreferences> {
  return fetchJson<ProfilePreferences>("/profile", {
    method: "PATCH",
    body: JSON.stringify(prefs),
  });
}
