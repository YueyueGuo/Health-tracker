import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./components/Dashboard";
import ActivityList from "./components/ActivityList";
import ActivityDetail from "./components/ActivityDetail";
import Sleep from "./components/Sleep";
import RecoveryPanel from "./components/RecoveryPanel";
import TrainingLoad from "./components/TrainingLoad";
import ChatPanel from "./components/ChatPanel";
import Settings from "./pages/Settings";
import Strength from "./pages/Strength";
import StrengthEntry from "./pages/StrengthEntry";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/activities" element={<ActivityList />} />
        <Route path="/activities/:id" element={<ActivityDetail />} />
        <Route path="/sleep" element={<Sleep />} />
        <Route path="/strength" element={<Strength />} />
        <Route path="/strength/new" element={<StrengthEntry />} />
        <Route path="/recovery" element={<RecoveryPanel />} />
        <Route path="/training" element={<TrainingLoad />} />
        <Route path="/ask" element={<ChatPanel />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
