import { useMemo, useState } from "react";
import {
  attachLocationToActivity,
  createLocation,
  detachLocationFromActivity,
} from "../api/locations";
import GpsLocationForm from "./location/GpsLocationForm";
import LocationSearchForm from "./location/LocationSearchForm";
import SavedLocationPicker from "./location/SavedLocationPicker";
import { useLocations } from "../hooks/useLocations";
import { formatElevation, useUnits } from "../hooks/useUnits";
import { getErrorMessage } from "../utils/errors";

interface Props {
  activityId: number;
  /** The currently-attached location id, when present. */
  currentLocationId: number | null;
  /** Called after a successful attach/detach so the parent can reload data. */
  onChange: () => void;
}

type Mode = "menu" | "saved" | "search" | "gps";

/**
 * Picker surface shown on activity detail for workouts without GPS coords.
 *
 * Three user-friendly entry paths (no raw lat/lng required):
 *   1. Pick a saved place (dropdown of user_locations).
 *   2. Search by name (text → Open-Meteo geocoding → list of candidates).
 *   3. Use current device location (navigator.geolocation).
 *
 * An "advanced" toggle still exposes explicit coords for completeness but
 * is intentionally tucked away.
 */
export default function LocationPicker({
  activityId,
  currentLocationId,
  onChange,
}: Props) {
  const { units } = useUnits();
  const [mode, setMode] = useState<Mode>("menu");
  const [loading, setLoading] = useState(false);
  const { locations, error, setError, setLocations } = useLocations();

  const currentLocation = useMemo(
    () =>
      currentLocationId == null
        ? null
        : locations?.find((l) => l.id === currentLocationId) ?? null,
    [locations, currentLocationId]
  );

  const attachById = async (id: number) => {
    setLoading(true);
    setError(null);
    try {
      await attachLocationToActivity(activityId, id);
      onChange();
      setMode("menu");
    } catch (error) {
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  const createAndAttach = async (
    name: string,
    lat: number,
    lng: number,
    elevation_m?: number | null
  ) => {
    setLoading(true);
    setError(null);
    try {
      const loc = await createLocation({
        name,
        lat,
        lng,
        elevation_m: elevation_m ?? null,
      });
      // Append to local list so repeat-picks don't need a round-trip.
      setLocations((prev) => (prev ? [...prev, loc] : [loc]));
      await attachLocationToActivity(activityId, loc.id);
      onChange();
      setMode("menu");
    } catch (error) {
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  const detach = async () => {
    setLoading(true);
    setError(null);
    try {
      await detachLocationFromActivity(activityId);
      onChange();
    } catch (error) {
      setError(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card" style={{ padding: 20 }}>
      <h3 style={{ marginTop: 0 }}>Location</h3>
      <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 4 }}>
        This workout has no GPS coordinates. Attach a place so we can
        determine your base altitude.
      </p>
      {currentLocation ? (
        <div style={{ marginBottom: 12 }}>
          <strong>{currentLocation.name}</strong>
          {currentLocation.elevation_m != null && (
            <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>
              · {formatElevation(currentLocation.elevation_m, units)}
            </span>
          )}
          <button
            className="btn btn-ghost"
            style={{ marginLeft: 12 }}
            onClick={detach}
            disabled={loading}
          >
            Clear
          </button>
        </div>
      ) : (
        <div style={{ color: "var(--text-muted)", marginBottom: 12 }}>
          No location attached.
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {mode === "menu" && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {locations && locations.length > 0 && (
            <button
              className="btn"
              onClick={() => setMode("saved")}
              disabled={loading}
            >
              Pick a saved place
            </button>
          )}
          <button
            className="btn"
            onClick={() => setMode("search")}
            disabled={loading}
          >
            Search by name
          </button>
          <button
            className="btn"
            onClick={() => setMode("gps")}
            disabled={loading}
          >
            Use my current location
          </button>
        </div>
      )}

      {mode === "saved" && locations && (
        <SavedLocationPicker
          locations={locations}
          onPick={attachById}
          onCancel={() => setMode("menu")}
        />
      )}

      {mode === "search" && (
        <LocationSearchForm
          onPick={(name, hit) =>
            createAndAttach(name, hit.lat, hit.lng, hit.elevation_m)
          }
          onCancel={() => setMode("menu")}
        />
      )}

      {mode === "gps" && (
        <GpsLocationForm
          busy={loading}
          intro={
            "We'll ask your browser for the current location and look up its elevation via Open-Meteo."
          }
          namePlaceholder="Name this place (e.g. Home gym)"
          saveLabel="Save & attach"
          onPick={(name, lat, lng) => createAndAttach(name, lat, lng)}
          onCancel={() => setMode("menu")}
        />
      )}
    </div>
  );
}
