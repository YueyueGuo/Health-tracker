import { Suspense, lazy } from "react";
import type { ReactElement } from "react";
import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";

const Dashboard = lazy(() => import("./components/Dashboard"));
const ActivityList = lazy(() => import("./components/ActivityList"));
const ActivityDetail = lazy(() => import("./components/ActivityDetail"));
const Sleep = lazy(() => import("./components/Sleep"));
const RecoveryPanel = lazy(() => import("./components/RecoveryPanel"));
const TrainingLoad = lazy(() => import("./components/TrainingLoad"));
const ChatPanel = lazy(() => import("./components/ChatPanel"));
const Settings = lazy(() => import("./pages/Settings"));
const Strength = lazy(() => import("./pages/Strength"));
const StrengthEntry = lazy(() => import("./pages/StrengthEntry"));

function routeElement(element: ReactElement) {
  return (
    <Suspense fallback={<div className="loading">Loading page...</div>}>
      {element}
    </Suspense>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={routeElement(<Dashboard />)} />
        <Route path="/activities" element={routeElement(<ActivityList />)} />
        <Route path="/activities/:id" element={routeElement(<ActivityDetail />)} />
        <Route path="/sleep" element={routeElement(<Sleep />)} />
        <Route path="/strength" element={routeElement(<Strength />)} />
        <Route path="/strength/new" element={routeElement(<StrengthEntry />)} />
        <Route path="/recovery" element={routeElement(<RecoveryPanel />)} />
        <Route path="/training" element={routeElement(<TrainingLoad />)} />
        <Route path="/ask" element={routeElement(<ChatPanel />)} />
        <Route path="/settings" element={routeElement(<Settings />)} />
      </Route>
    </Routes>
  );
}
