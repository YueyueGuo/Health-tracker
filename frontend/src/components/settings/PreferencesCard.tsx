import { Scale } from "lucide-react";
import { Card } from "../ui/Card";
import { useUnits, type UnitSystem } from "../../hooks/useUnits";

/**
 * Settings → Preferences card: segmented Imperial / Metric toggle.
 * Persists through the shared `useUnits` context (localStorage key
 * `ht.units`). The dashboard chrome and all distance/speed/weight
 * formatters read from the same hook so this is the single source of
 * truth for the user's unit choice.
 */
export default function PreferencesCard() {
  const { units, setUnits } = useUnits();

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-4">
        <Scale size={16} className="text-slate-300" />
        <h3 className="text-sm font-semibold text-slate-200">Preferences</h3>
      </div>

      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-200">Units</div>
          <div className="text-[11px] text-slate-500">
            Weight, distance, and speed
          </div>
        </div>
        <div
          className="flex bg-dashboard border border-cardBorder rounded-lg p-1"
          role="group"
          aria-label="Units"
        >
          <UnitButton
            label="Imperial"
            value="imperial"
            current={units}
            onClick={() => setUnits("imperial")}
          />
          <UnitButton
            label="Metric"
            value="metric"
            current={units}
            onClick={() => setUnits("metric")}
          />
        </div>
      </div>
    </Card>
  );
}

interface UnitButtonProps {
  label: string;
  value: UnitSystem;
  current: UnitSystem;
  onClick: () => void;
}

function UnitButton({ label, value, current, onClick }: UnitButtonProps) {
  const active = current === value;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
        active
          ? "bg-cardBorder text-white shadow-sm"
          : "text-slate-400 hover:text-slate-200"
      }`}
    >
      {label}
    </button>
  );
}
