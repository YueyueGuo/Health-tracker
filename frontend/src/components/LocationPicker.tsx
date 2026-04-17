import { useEffect, useMemo, useRef, useState } from "react";
import {
  attachLocationToActivity,
  createLocation,
  detachLocationFromActivity,
  listLocations,
  searchLocations,
  type Location,
  type LocationSearchHit,
} from "../api/locations";
import { formatElevation, useUnits } from "../hooks/useUnits";

interface Props {
  activityId: number;
  /** The currently-attached location id, if any. */
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
  const [locations, setLocations] = useState<Location[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listLocations()
      .then((rows) => {
        if (!cancelled) setLocations(rows);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? "Failed to load locations");
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
    } catch (e) {
      setError(extractMessage(e));
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
    } catch (e) {
      setError(extractMessage(e));
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
    } catch (e) {
      setError(extractMessage(e));
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
        <SavedPicker
          locations={locations}
          onPick={attachById}
          onCancel={() => setMode("menu")}
        />
      )}

      {mode === "search" && (
        <SearchPicker
          onPick={(hit, displayName) =>
            createAndAttach(displayName, hit.lat, hit.lng, hit.elevation_m)
          }
          onCancel={() => setMode("menu")}
        />
      )}

      {mode === "gps" && (
        <GpsPicker
          onPick={(name, lat, lng) => createAndAttach(name, lat, lng)}
          onCancel={() => setMode("menu")}
        />
      )}
    </div>
  );
}

// ── Sub-pickers ───────────────────────────────────────────────────────

function SavedPicker({
  locations,
  onPick,
  onCancel,
}: {
  locations: Location[];
  onPick: (id: number) => void;
  onCancel: () => void;
}) {
  const { units } = useUnits();
  return (
    <div style={{ marginTop: 12 }}>
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {locations.map((loc) => (
          <li key={loc.id}>
            <button
              className="btn btn-ghost"
              style={{ width: "100%", textAlign: "left" }}
              onClick={() => onPick(loc.id)}
            >
              <strong>{loc.name}</strong>
              {loc.is_default && (
                <span className="chip" style={{ marginLeft: 8 }}>
                  default
                </span>
              )}
              {loc.elevation_m != null && (
                <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>
                  · {formatElevation(loc.elevation_m, units)}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
      <div style={{ marginTop: 8 }}>
        <button className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function SearchPicker({
  onPick,
  onCancel,
}: {
  onPick: (hit: LocationSearchHit, displayName: string) => void;
  onCancel: () => void;
}) {
  const { units } = useUnits();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<LocationSearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q.trim()) {
      setResults(null);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      setError(null);
      try {
        const rows = await searchLocations(q.trim(), 5);
        setResults(rows);
      } catch (e) {
        setError(extractMessage(e));
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [q]);

  return (
    <div style={{ marginTop: 12 }}>
      <input
        autoFocus
        placeholder="e.g. Boulder, CO"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ width: "100%", padding: "6px 10px" }}
      />
      {searching && (
        <div style={{ color: "var(--text-muted)", marginTop: 8 }}>
          Searching…
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {results && results.length === 0 && !searching && (
        <div style={{ color: "var(--text-muted)", marginTop: 8 }}>
          No matches.
        </div>
      )}
      {results && results.length > 0 && (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: "8px 0 0 0",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          {results.map((hit, idx) => {
            const label = formatSearchHit(hit);
            return (
              <li key={`${hit.lat},${hit.lng},${idx}`}>
                <button
                  className="btn btn-ghost"
                  style={{ width: "100%", textAlign: "left" }}
                  onClick={() => onPick(hit, label)}
                >
                  <strong>{label}</strong>
                  {hit.elevation_m != null && (
                    <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>
                      · {formatElevation(hit.elevation_m, units)}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div style={{ marginTop: 8 }}>
        <button className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function GpsPicker({
  onPick,
  onCancel,
}: {
  onPick: (name: string, lat: number, lng: number) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);

  const requestCoords = () => {
    if (!("geolocation" in navigator)) {
      setError("Geolocation is not available in this browser.");
      return;
    }
    setFetching(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
        });
        setFetching(false);
      },
      (err) => {
        setError(err.message || "Failed to get current location.");
        setFetching(false);
      },
      { enableHighAccuracy: true, timeout: 10_000 }
    );
  };

  return (
    <div style={{ marginTop: 12 }}>
      {!coords && (
        <>
          <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
            We'll ask your browser for the current location and look up its
            elevation via Open-Meteo.
          </p>
          <button
            className="btn"
            onClick={requestCoords}
            disabled={fetching}
          >
            {fetching ? "Getting location…" : "Get current location"}
          </button>
        </>
      )}
      {coords && (
        <>
          <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
            Got it: {coords.lat.toFixed(5)}, {coords.lng.toFixed(5)}
          </div>
          <input
            autoFocus
            placeholder="Name this place (e.g. Home gym)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ width: "100%", padding: "6px 10px", marginTop: 8 }}
          />
          <div style={{ marginTop: 8 }}>
            <button
              className="btn"
              disabled={!name.trim()}
              onClick={() => onPick(name.trim(), coords.lat, coords.lng)}
            >
              Save &amp; attach
            </button>
          </div>
        </>
      )}
      {error && <div className="error">{error}</div>}
      <div style={{ marginTop: 8 }}>
        <button className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── helpers ───────────────────────────────────────────────────────────

function formatSearchHit(hit: LocationSearchHit): string {
  return [hit.name, hit.admin1, hit.country].filter(Boolean).join(", ");
}

function extractMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}
