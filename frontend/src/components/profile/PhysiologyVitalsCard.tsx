import { Activity } from "lucide-react";
import { Card } from "../ui/Card";
import type { ProfileVitals } from "../../hooks/useProfilePreferences";

interface PhysiologyVitalsCardProps {
  vitals: ProfileVitals;
  onChange: (vitals: ProfileVitals) => void;
}

type VitalField = keyof ProfileVitals;

const SUMMARY_FIELDS: Array<{
  key: VitalField;
  label: string;
  suffix?: string;
  inputMode?: "numeric" | "text";
}> = [
  { key: "age", label: "Age", inputMode: "numeric" },
  { key: "weight", label: "Weight", suffix: "lb", inputMode: "numeric" },
  { key: "height", label: "Height", inputMode: "text" },
];

const HEART_RATE_FIELDS: Array<{
  key: VitalField;
  label: string;
}> = [
  { key: "maxHr", label: "Max HR" },
  { key: "lthr", label: "LTHR" },
];

export default function PhysiologyVitalsCard({
  vitals,
  onChange,
}: PhysiologyVitalsCardProps) {
  function update(key: VitalField, value: string) {
    onChange({ ...vitals, [key]: value });
  }

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-4">
        <Activity size={16} className="text-slate-300" />
        <h3 className="text-sm font-semibold text-slate-200">
          Physiology & Vitals
        </h3>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-4">
        {SUMMARY_FIELDS.map((field) => (
          <label
            key={field.key}
            className="bg-dashboard/50 p-2 rounded-lg border border-cardBorder/50 text-center"
          >
            <span className="block text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">
              {field.label}
            </span>
            <span className="flex items-baseline justify-center gap-1">
              <input
                aria-label={field.label}
                value={vitals[field.key]}
                inputMode={field.inputMode}
                onChange={(event) => update(field.key, event.target.value)}
                className="w-full min-w-0 bg-transparent text-center text-sm font-bold text-white focus:outline-none"
              />
              {field.suffix && (
                <span className="text-[10px] font-normal text-slate-500">
                  {field.suffix}
                </span>
              )}
            </span>
          </label>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3">
        {HEART_RATE_FIELDS.map((field) => (
          <label
            key={field.key}
            className="flex justify-between items-center gap-3 p-2 rounded-lg bg-dashboard/30 border border-cardBorder/30"
          >
            <span className="text-xs text-slate-400">{field.label}</span>
            <span className="flex items-baseline justify-end gap-1">
              <input
                aria-label={field.label}
                value={vitals[field.key]}
                inputMode="numeric"
                onChange={(event) => update(field.key, event.target.value)}
                className="w-14 bg-transparent text-right text-sm font-semibold text-white focus:outline-none"
              />
              <span className="text-[10px] text-slate-500">bpm</span>
            </span>
          </label>
        ))}
      </div>
    </Card>
  );
}
