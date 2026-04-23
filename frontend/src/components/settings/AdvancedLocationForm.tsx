import { useState } from "react";

interface Props {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (
    name: string,
    lat: number,
    lng: number,
    elevation_m?: number | null
  ) => void;
}

export default function AdvancedLocationForm({
  busy,
  onCancel,
  onSubmit,
}: Props) {
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
