import { useState } from "react";
import { createLocation } from "../../api/locations";
import GpsLocationForm from "../location/GpsLocationForm";
import LocationSearchForm from "../location/LocationSearchForm";
import { getErrorMessage } from "../../utils/errors";
import AdvancedLocationForm from "./AdvancedLocationForm";

type AddLocationMode = "idle" | "search" | "gps" | "advanced";

export default function AddLocation({ onAdded }: { onAdded: () => void }) {
  const [mode, setMode] = useState<AddLocationMode>("idle");
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
    } catch (error) {
      setError(getErrorMessage(error));
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
        <LocationSearchForm
          busy={busy}
          requireName
          onCancel={() => setMode("idle")}
          onPick={(name, hit) =>
            submit(name, hit.lat, hit.lng, hit.elevation_m)
          }
        />
      )}
      {mode === "gps" && (
        <GpsLocationForm
          busy={busy}
          onCancel={() => setMode("idle")}
          onPick={submit}
        />
      )}
      {mode === "advanced" && (
        <AdvancedLocationForm
          busy={busy}
          onCancel={() => setMode("idle")}
          onSubmit={submit}
        />
      )}
    </div>
  );
}
