import { useState } from "react";

export interface CurrentPosition {
  lat: number;
  lng: number;
}

export function useCurrentPosition() {
  const [coords, setCoords] = useState<CurrentPosition | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);

  const requestPosition = () => {
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

  const reset = () => {
    setCoords(null);
    setError(null);
    setFetching(false);
  };

  return { coords, error, fetching, requestPosition, reset };
}
