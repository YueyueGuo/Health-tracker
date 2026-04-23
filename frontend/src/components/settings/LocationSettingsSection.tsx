import AddLocation from "./AddLocation";
import LocationRow from "./LocationRow";
import { useLocations } from "../../hooks/useLocations";
import { useUnits } from "../../hooks/useUnits";

export default function LocationSettingsSection() {
  const { units } = useUnits();
  const { locations, error, reload } = useLocations();

  return (
    <>
      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <h2 style={{ marginTop: 0 }}>Add a location</h2>
        <AddLocation onAdded={reload} />
      </div>

      <div className="card" style={{ padding: 0 }}>
        <h2 style={{ padding: "20px 24px 12px" }}>Saved locations</h2>
        {error && (
          <div className="error" style={{ margin: "0 24px 12px" }}>
            {error}
          </div>
        )}
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
              {locations.map((location) => (
                <LocationRow
                  key={location.id}
                  location={location}
                  units={units}
                  onChange={reload}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
