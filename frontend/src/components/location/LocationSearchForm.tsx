import { useState } from "react";
import type { LocationSearchHit } from "../../api/locations";
import { useDebouncedLocationSearch } from "../../hooks/useDebouncedLocationSearch";
import { formatElevation, useUnits } from "../../hooks/useUnits";

interface Props {
  busy?: boolean;
  requireName?: boolean;
  saveLabel?: string;
  onCancel: () => void;
  onPick: (name: string, hit: LocationSearchHit) => void;
}

export default function LocationSearchForm({
  busy = false,
  requireName = false,
  saveLabel = "Save",
  onCancel,
  onPick,
}: Props) {
  const { units } = useUnits();
  const [q, setQ] = useState("");
  const [pickedName, setPickedName] = useState("");
  const [picked, setPicked] = useState<LocationSearchHit | null>(null);
  const { results, searching, error } = useDebouncedLocationSearch(q);

  if (picked && requireName) {
    return (
      <div style={{ marginTop: 12 }}>
        <LocationHitSummary hit={picked} />
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
            onClick={() => onPick(pickedName.trim(), picked)}
          >
            {saveLabel}
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
            const label = formatLocationSearchHit(hit);
            return (
              <li key={`${hit.lat},${hit.lng},${idx}`}>
                <button
                  className="btn btn-ghost"
                  style={{ width: "100%", textAlign: "left" }}
                  onClick={() => {
                    if (requireName) {
                      setPicked(hit);
                      setPickedName(hit.name ?? "");
                    } else {
                      onPick(label, hit);
                    }
                  }}
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

function formatLocationSearchHit(hit: LocationSearchHit): string {
  return [hit.name, hit.admin1, hit.country].filter(Boolean).join(", ");
}

function LocationHitSummary({ hit }: { hit: LocationSearchHit }) {
  const { units } = useUnits();
  return (
    <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
      {formatLocationSearchHit(hit)}
      {hit.elevation_m != null && (
        <> &middot; {formatElevation(hit.elevation_m, units)}</>
      )}
    </div>
  );
}
