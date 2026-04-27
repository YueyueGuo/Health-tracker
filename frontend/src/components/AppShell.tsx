import { Outlet } from "react-router-dom";
import { BottomNav } from "./dashboard/BottomNav";

export default function AppShell() {
  return (
    <div className="min-h-screen w-full bg-dashboard text-slate-200 font-sans pb-24">
      <div className="max-w-2xl mx-auto px-4 sm:px-6">
        <Outlet />
      </div>
      <BottomNav />
    </div>
  );
}
