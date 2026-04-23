import { useEffect, useState } from "react";
import { listLocations, type Location } from "../api/locations";
import { getErrorMessage } from "../utils/errors";

export function useLocations() {
  const [locations, setLocations] = useState<Location[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    try {
      const rows = await listLocations();
      setLocations(rows);
      setError(null);
    } catch (error) {
      setError(getErrorMessage(error));
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  return { locations, error, reload, setLocations, setError };
}
