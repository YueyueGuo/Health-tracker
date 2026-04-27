import { Outlet } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import { fetchDashboardToday } from "../api/dashboard";
import type { DashboardToday } from "../api/dashboard";
import { Header } from "./dashboard/Header";
import { EnvironmentBar } from "./dashboard/EnvironmentBar";
import { BottomNav } from "./dashboard/BottomNav";

export interface HomeOutletContext {
  today: DashboardToday | null;
  todayLoading: boolean;
  todayError: string | null;
  reloadToday: () => Promise<void>;
}

export default function HomeLayout() {
  const { data, loading, error, reload } = useApi(fetchDashboardToday);

  const ctx: HomeOutletContext = {
    today: data,
    todayLoading: loading,
    todayError: error,
    reloadToday: reload,
  };

  return (
    <div className="min-h-screen w-full bg-dashboard text-slate-200 font-sans pb-24">
      <div className="max-w-2xl mx-auto px-4 sm:px-6">
        <div className="sticky top-0 z-20 bg-dashboard/95 backdrop-blur-md pb-1 -mx-4 px-4 sm:mx-0 sm:px-0">
          <Header />
          <EnvironmentBar data={data?.environment ?? null} />
        </div>

        <Outlet context={ctx} />
      </div>

      <BottomNav />
    </div>
  );
}
