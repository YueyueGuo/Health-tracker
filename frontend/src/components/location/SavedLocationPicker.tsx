import { type Location } from "../../api/locations";
import { formatElevation, useUnits } from "../../hooks/useUnits";

interface Props {
  locations: Location[];
  onPick: (id: number) => void;
  onCancel: () => void;
}

export default function SavedLocationPicker({
  locations,
  onPick,
  onCancel,
}: Props) {
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
        {locations.map((location) => (
          <li key={location.id}>
            <button
              className="btn btn-ghost"
              style={{ width: "100%", textAlign: "left" }}
              onClick={() => onPick(location.id)}
            >
              <strong>{location.name}</strong>
              {location.is_default && (
                <span className="chip" style={{ marginLeft: 8 }}>
                  default
                </span>
              )}
              {location.elevation_m != null && (
                <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>
                  · {formatElevation(location.elevation_m, units)}
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
