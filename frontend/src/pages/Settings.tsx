import { ChevronLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import AccountCard from "../components/settings/AccountCard";
import PreferencesCard from "../components/settings/PreferencesCard";
import GearCard from "../components/settings/GearCard";
import AdvancedSection from "../components/settings/AdvancedSection";
import DataSourcesCard from "../components/profile/DataSourcesCard";

/**
 * Settings page, served under `AppShell` (same chrome as Profile).
 *
 * Layout:
 *   1. Sticky header  →  back arrow + "Settings" title.
 *   2. Account card   →  display name, email, dateOfBirth.
 *   3. Preferences    →  units toggle (single source of truth).
 *   4. Gear           →  shoes shortcut.
 *   5. Data sources   →  live integration health (moved off Profile).
 *   6. Advanced       →  collapsible: goals / locations / raw sync.
 */
export default function Settings() {
  const navigate = useNavigate();

  return (
    <div className="pb-24 pt-2 animate-in slide-in-from-right-4 duration-300">
      <div className="sticky top-0 z-10 bg-dashboard/95 backdrop-blur-md px-1 py-3 mb-4 flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate(-1)}
          aria-label="Back"
          className="p-2 text-slate-400 hover:text-white transition-colors bg-cardBorder/30 rounded-full"
        >
          <ChevronLeft size={16} />
        </button>
        <h1 className="text-2xl font-bold text-white tracking-tight">
          Settings
        </h1>
      </div>

      <div className="space-y-4">
        <AccountCard />
        <PreferencesCard />
        <GearCard />
        <DataSourcesCard />
        <AdvancedSection />
      </div>
    </div>
  );
}
