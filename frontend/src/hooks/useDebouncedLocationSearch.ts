import { useEffect, useState } from "react";
import {
  searchLocations,
  type LocationSearchHit,
} from "../api/locations";
import { getErrorMessage } from "../utils/errors";

export function useDebouncedLocationSearch(
  query: string,
  count = 5,
  delayMs = 300
) {
  const [results, setResults] = useState<LocationSearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults(null);
      setSearching(false);
      setError(null);
      return;
    }

    let active = true;
    const timeout = window.setTimeout(async () => {
      setSearching(true);
      setError(null);
      try {
        const rows = await searchLocations(trimmed, count);
        if (active) setResults(rows);
      } catch (error) {
        if (active) setError(getErrorMessage(error));
      } finally {
        if (active) setSearching(false);
      }
    }, delayMs);

    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [query, count, delayMs]);

  return { results, searching, error };
}
