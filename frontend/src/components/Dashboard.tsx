import { useState } from "react";
import { useApi } from "../hooks/useApi";
import { fetchDashboardToday } from "../api/dashboard";
import { triggerSync } from "../api/sync";
import WeeklySummaryCards from "./WeeklySummaryCards";
import RecommendationCard from "./RecommendationCard";
import LatestWorkoutCard from "./LatestWorkoutCard";
import SleepTile from "./dashboard/SleepTile";
import RecoveryTile from "./dashboard/RecoveryTile";
import TrainingLoadTile from "./dashboard/TrainingLoadTile";
import EnvironmentTile from "./dashboard/EnvironmentTile";

export default function Dashboard() {
  const { data, loading, error, reload } = useApi(fetchDashboardToday);
  const [syncing, setSyncing] = useState(false);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await triggerSync("all");
      await reload();
    } finally {
      setSyncing(false);
    }
  };

  if (loading) return <div className="loading">Loading dashboard...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!data) return null;

  return (
    <div>
      <div className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1>Dashboard</h1>
          <p>Your health & fitness overview</p>
        </div>
        <button className="btn" onClick={handleSync} disabled={syncing}>
          {syncing ? "Syncing..." : "Sync Data"}
        </button>
      </div>

      <RecommendationCard />
      <LatestWorkoutCard />

      <div className="metric-grid">
        <SleepTile data={data.sleep} />
        <RecoveryTile data={data.recovery} />
        <TrainingLoadTile data={data.training} />
        <EnvironmentTile data={data.environment} />
      </div>

      <WeeklySummaryCards weeks={4} />
    </div>
  );
}
