import { useState } from "react";
import { useCurrentPosition } from "../../hooks/useCurrentPosition";

interface Props {
  busy?: boolean;
  intro?: string;
  namePlaceholder?: string;
  saveLabel?: string;
  onCancel: () => void;
  onPick: (name: string, lat: number, lng: number) => void;
}

export default function GpsLocationForm({
  busy = false,
  intro,
  namePlaceholder = "Name this location (e.g. Home)",
  saveLabel = "Save",
  onCancel,
  onPick,
}: Props) {
  const [name, setName] = useState("");
  const { coords, error, fetching, requestPosition, reset } = useCurrentPosition();

  return (
    <div style={{ marginTop: 12 }}>
      {!coords && (
        <>
          {intro && (
            <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
              {intro}
            </p>
          )}
          <button className="btn" onClick={requestPosition} disabled={fetching}>
            {fetching ? "Getting location…" : "Get current location"}
          </button>
        </>
      )}
      {coords && (
        <>
          <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
            {coords.lat.toFixed(5)}, {coords.lng.toFixed(5)}
          </div>
          <input
            autoFocus
            placeholder={namePlaceholder}
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ width: "100%", padding: "6px 10px", marginTop: 8 }}
          />
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <button
              className="btn"
              disabled={busy || !name.trim()}
              onClick={() => onPick(name.trim(), coords.lat, coords.lng)}
            >
              {saveLabel}
            </button>
            <button className="btn btn-ghost" onClick={reset}>
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
