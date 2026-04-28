import { Suspense, lazy } from "react";
import type { ReactElement } from "react";
import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import HomeLayout from "./components/HomeLayout";
import AppShell from "./components/AppShell";

const Dashboard = lazy(() => import("./components/Dashboard"));
const ActivityDetail = lazy(() => import("./components/ActivityDetail"));
const Sleep = lazy(() => import("./components/Sleep"));
const RecoveryPanel = lazy(() => import("./components/RecoveryPanel"));
const TrainingLoad = lazy(() => import("./components/TrainingLoad"));
const ChatPanel = lazy(() => import("./components/ChatPanel"));
const Settings = lazy(() => import("./pages/Settings"));
const Record = lazy(() => import("./pages/Record"));
const History = lazy(() => import("./pages/History"));

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
      <Route element={<HomeLayout />}>
        <Route path="/" element={routeElement(<Dashboard />)} />
      </Route>
      <Route element={<AppShell />}>
        <Route path="/record" element={routeElement(<Record />)} />
        <Route path="/history" element={routeElement(<History />)} />
        <Route path="/activities/:id" element={routeElement(<ActivityDetail />)} />
      </Route>
      <Route element={<Layout />}>
        <Route path="/sleep" element={routeElement(<Sleep />)} />
        <Route path="/recovery" element={routeElement(<RecoveryPanel />)} />
        <Route path="/training" element={routeElement(<TrainingLoad />)} />
        <Route path="/ask" element={routeElement(<ChatPanel />)} />
        <Route path="/settings" element={routeElement(<Settings />)} />
      </Route>
    </Routes>
  );
}
