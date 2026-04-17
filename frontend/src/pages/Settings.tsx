import { useEffect, useRef, useState } from "react";
import {
  createLocation,
  deleteLocation,
  listLocations,
  patchLocation,
  searchLocations,
  setDefaultLocation,
  type Location,
  type LocationSearchHit,
} from "../api/locations";
import { formatElevation, useUnits } from "../hooks/useUnits";

/**
 * Settings page: manage your saved ``user_locations``.
 *
 * Entry paths mirror the LocationPicker so the UX is consistent:
 *  - Search by name (Open-Meteo geocoding \u2192 pick a candidate).
 *  - Use current device location (``navigator.geolocation``).
 *  - Advanced: enter raw lat/lng (rare \u2014 for pinning exact spots).
 *
 * Additional list affordances: set-default, rename, delete.
 */
export default function Settings() {
  const { units } = useUnits();
  const [locations, setLocations] = useState<Location[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    try {
      const rows = await listLocations();
      setLocations(rows);
    } catch (e) {
      setError(extractMessage(e));
    }
  };

  useEffect(() => {
    reload();
  }, []);

  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
        <p>Saved places used to attach base altitude to indoor workouts.</p>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <h2 style={{ marginTop: 0 }}>Add a location</h2>
        <AddLocation onAdded={reload} />
      </div>

      <div className="card" style={{ padding: 0 }}>
        <h2 style={{ padding: "20px 24px 12px" }}>Saved locations</h2>
        {!locations && <div className="loading">Loading…</div>}
        {locations && locations.length === 0 && (
          <div style={{ padding: "0 24px 20px", color: "var(--text-muted)" }}>
            No saved locations yet.
          </div>
        )}
        {locations && locations.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Elevation</th>
                <th>Coords</th>
                <th>Default</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {locations.map((loc) => (
                <LocationRow
                  key={loc.id}
                  loc={loc}
                  units={units}
                  onChange={reload}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── Row ───────────────────────────────────────────────────────────────

function LocationRow({
  loc,
  units,
  onChange,
}: {
  loc: Location;
  units: "imperial" | "metric";
  onChange: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(loc.name);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!name.trim() || name === loc.name) {
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      await patchLocation(loc.id, { name: name.trim() });
      onChange();
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirm(`Delete "${loc.name}"?`)) return;
    setBusy(true);
    try {
      await deleteLocation(loc.id);
      onChange();
    } finally {
      setBusy(false);
    }
  };

  const makeDefault = async () => {
    setBusy(true);
    try {
      await setDefaultLocation(loc.id);
      onChange();
    } finally {
      setBusy(false);
    }
  };

  const unsetDefault = async () => {
    setBusy(true);
    try {
      await patchLocation(loc.id, { is_default: false });
      onChange();
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr>
      <td>
        {editing ? (
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
              if (e.key === "Escape") {
                setName(loc.name);
                setEditing(false);
              }
            }}
          />
        ) : (
          <button
            className="btn btn-ghost"
            onClick={() => setEditing(true)}
            style={{ padding: 0 }}
          >
            <strong>{loc.name}</strong>
          </button>
        )}
      </td>
      <td>{formatElevation(loc.elevation_m, units)}</td>
      <td style={{ color: "var(--text-muted)", fontSize: 12 }}>
        {loc.lat.toFixed(4)}, {loc.lng.toFixed(4)}
      </td>
      <td>
        {loc.is_default ? (
          <button
            className="btn btn-ghost"
            disabled={busy}
            onClick={unsetDefault}
          >
            <span className="chip">default</span>
          </button>
        ) : (
          <button className="btn btn-ghost" disabled={busy} onClick={makeDefault}>
            Make default
          </button>
        )}
      </td>
      <td>
        <button className="btn btn-ghost" disabled={busy} onClick={remove}>
          Delete
        </button>
      </td>
    </tr>
  );
}

// ── Add location (three entry paths + advanced) ───────────────────────

type AddMode = "idle" | "search" | "gps" | "advanced";

function AddLocation({ onAdded }: { onAdded: () => void }) {
  const [mode, setMode] = useState<AddMode>("idle");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (
    name: string,
    lat: number,
    lng: number,
    elevation_m?: number | null
  ) => {
    setBusy(true);
    setError(null);
    try {
      await createLocation({
        name,
        lat,
        lng,
        elevation_m: elevation_m ?? null,
      });
      onAdded();
      setMode("idle");
    } catch (e) {
      setError(extractMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      {mode === "idle" && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn" onClick={() => setMode("search")}>
            Search by name
          </button>
          <button className="btn" onClick={() => setMode("gps")}>
            Use my current location
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => setMode("advanced")}
          >
            Enter coords manually
          </button>
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {mode === "search" && (
        <SearchForm
          busy={busy}
          onCancel={() => setMode("idle")}
          onPick={submit}
        />
      )}
      {mode === "gps" && (
        <GpsForm
          busy={busy}
          onCancel={() => setMode("idle")}
          onSubmit={submit}
        />
      )}
      {mode === "advanced" && (
        <AdvancedForm
          busy={busy}
          onCancel={() => setMode("idle")}
          onSubmit={submit}
        />
      )}
    </div>
  );
}

function SearchForm({
  busy,
  onCancel,
  onPick,
}: {
  busy: boolean;
  onCancel: () => void;
  onPick: (
    name: string,
    lat: number,
    lng: number,
    elevation_m?: number | null
  ) => void;
}) {
  const { units } = useUnits();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<LocationSearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [pickedName, setPickedName] = useState<string>("");
  const [picked, setPicked] = useState<LocationSearchHit | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q.trim()) {
      setResults(null);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        setResults(await searchLocations(q.trim(), 5));
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [q]);

  if (picked) {
    return (
      <div style={{ marginTop: 12 }}>
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
          {[picked.name, picked.admin1, picked.country]
            .filter(Boolean)
            .join(", ")}
          {picked.elevation_m != null && (
            <> &middot; {formatElevation(picked.elevation_m, units)}</>
          )}
        </div>
        <input
          autoFocus
          placeholder="Name this location (e.g. Tahoe cabin)"
          value={pickedName}
          onChange={(e) => setPickedName(e.target.value)}
          style={{ width: "100%", padding: "6px 10px", marginTop: 8 }}
        />
        <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
          <button
            className="btn"
            disabled={busy || !pickedName.trim()}
            onClick={() =>
              onPick(
                pickedName.trim(),
                picked.lat,
                picked.lng,
                picked.elevation_m
              )
            }
          >
            Save
          </button>
          <button className="btn btn-ghost" onClick={() => setPicked(null)}>
            Back
          </button>
        </div>
      </div>
    );
  }

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
          {results.map((hit, idx) => (
            <li key={`${hit.lat},${hit.lng},${idx}`}>
              <button
                className="btn btn-ghost"
                style={{ width: "100%", textAlign: "left" }}
                onClick={() => {
                  setPicked(hit);
                  setPickedName(hit.name ?? "");
                }}
              >
                <strong>
                  {[hit.name, hit.admin1, hit.country]
                    .filter(Boolean)
                    .join(", ")}
                </strong>
                {hit.elevation_m != null && (
                  <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>
                    · {formatElevation(hit.elevation_m, units)}
                  </span>
                )}
              </button>
            </li>
          ))}
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

function GpsForm({
  busy,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (name: string, lat: number, lng: number) => void;
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
        setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude });
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
        <button className="btn" onClick={requestCoords} disabled={fetching}>
          {fetching ? "Getting location…" : "Get current location"}
        </button>
      )}
      {coords && (
        <>
          <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
            {coords.lat.toFixed(5)}, {coords.lng.toFixed(5)}
          </div>
          <input
            autoFocus
            placeholder="Name this location (e.g. Home)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ width: "100%", padding: "6px 10px", marginTop: 8 }}
          />
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <button
              className="btn"
              disabled={busy || !name.trim()}
              onClick={() => onSubmit(name.trim(), coords.lat, coords.lng)}
            >
              Save
            </button>
            <button className="btn btn-ghost" onClick={() => setCoords(null)}>
              Retry
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

function AdvancedForm({
  busy,
  onCancel,
  onSubmit,
}: {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (
    name: string,
    lat: number,
    lng: number,
    elevation_m?: number | null
  ) => void;
}) {
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [elev, setElev] = useState("");

  const latNum = Number(lat);
  const lngNum = Number(lng);
  const elevNum = elev.trim() === "" ? null : Number(elev);

  const canSubmit =
    name.trim() !== "" &&
    Number.isFinite(latNum) &&
    Number.isFinite(lngNum) &&
    Math.abs(latNum) <= 90 &&
    Math.abs(lngNum) <= 180 &&
    (elevNum === null || Number.isFinite(elevNum));

  return (
    <div style={{ marginTop: 12, display: "grid", gap: 8, maxWidth: 360 }}>
      <input
        placeholder="Name"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <input
        placeholder="Latitude (e.g. 37.7749)"
        value={lat}
        onChange={(e) => setLat(e.target.value)}
        inputMode="decimal"
      />
      <input
        placeholder="Longitude (e.g. -122.4194)"
        value={lng}
        onChange={(e) => setLng(e.target.value)}
        inputMode="decimal"
      />
      <input
        placeholder="Elevation in meters (optional)"
        value={elev}
        onChange={(e) => setElev(e.target.value)}
        inputMode="decimal"
      />
      <div style={{ display: "flex", gap: 8 }}>
        <button
          className="btn"
          disabled={busy || !canSubmit}
          onClick={() =>
            onSubmit(name.trim(), latNum, lngNum, elevNum ?? undefined)
          }
        >
          Save
        </button>
        <button className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── helpers ───────────────────────────────────────────────────────────

function extractMessage(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}
