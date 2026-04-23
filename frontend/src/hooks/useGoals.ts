import { useEffect, useState } from "react";
import { listGoals, type Goal } from "../api/goals";
import { getErrorMessage } from "../utils/errors";

export function useGoals() {
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    try {
      const rows = await listGoals();
      setGoals(rows);
      setError(null);
    } catch (error) {
      setError(getErrorMessage(error));
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  return { goals, error, reload, setGoals, setError };
}
