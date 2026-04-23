import { useState } from "react";
import {
  deleteLocation,
  patchLocation,
  setDefaultLocation,
  type Location,
} from "../../api/locations";
import { formatElevation, type UnitSystem } from "../../hooks/useUnits";

export default function LocationRow({
  location,
  units,
  onChange,
}: {
  location: Location;
  units: UnitSystem;
  onChange: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(location.name);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!name.trim() || name === location.name) {
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      await patchLocation(location.id, { name: name.trim() });
      onChange();
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirm(`Delete "${location.name}"?`)) return;
    setBusy(true);
    try {
      await deleteLocation(location.id);
      onChange();
    } finally {
      setBusy(false);
    }
  };

  const makeDefault = async () => {
    setBusy(true);
    try {
      await setDefaultLocation(location.id);
      onChange();
    } finally {
      setBusy(false);
    }
  };

  const unsetDefault = async () => {
    setBusy(true);
    try {
      await patchLocation(location.id, { is_default: false });
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
              if (e.key === "Enter") void save();
              if (e.key === "Escape") {
                setName(location.name);
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
            <strong>{location.name}</strong>
          </button>
        )}
      </td>
      <td>{formatElevation(location.elevation_m, units)}</td>
      <td style={{ color: "var(--text-muted)", fontSize: 12 }}>
        {location.lat.toFixed(4)}, {location.lng.toFixed(4)}
      </td>
      <td>
        {location.is_default ? (
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
