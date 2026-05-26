import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import { Card } from "../ui/Card";
import GoalsSection from "../GoalsSection";
import LocationSettingsSection from "./LocationSettingsSection";
import SyncSection from "./SyncSection";

/**
 * Settings → Advanced expander. Collapsed by default. Houses the
 * legacy sections (Goals, Locations, raw sync controls) that the
 * day-to-day user shouldn't see, but which the project owner still
 * needs while the integration cards mature.
 */
export default function AdvancedSection() {
  const [open, setOpen] = useState(false);

  return (
    <Card className="p-4">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-controls="advanced-section-body"
        className="w-full flex items-center justify-between gap-3 text-left"
      >
        <span className="flex items-center gap-2">
          <Wrench size={16} className="text-slate-300" />
          <span className="text-sm font-semibold text-slate-200">Advanced</span>
        </span>
        {open ? (
          <ChevronDown size={16} className="text-slate-500" />
        ) : (
          <ChevronRight size={16} className="text-slate-500" />
        )}
      </button>

      {open && (
        <div id="advanced-section-body" className="mt-4 space-y-4">
          <GoalsSection />
          <LocationSettingsSection />
          <SyncSection />
        </div>
      )}
    </Card>
  );
}
