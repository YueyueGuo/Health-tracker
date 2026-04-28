import { Check, Sparkles } from "lucide-react";
import { Card } from "../ui/Card";
import {
  DURATION_OPTIONS,
  EQUIPMENT_OPTIONS,
  FOCUS_OPTIONS,
  FREQUENCY_OPTIONS,
  LIMITATION_OPTIONS,
  normalizeLimitations,
  type EquipmentOption,
  type LimitationOption,
  type ProfilePreferences,
  type TrainingDuration,
  type TrainingFocus,
  type TrainingFrequency,
} from "../../hooks/useProfilePreferences";

interface CoachingDirectivesCardProps {
  preferences: ProfilePreferences;
  onChange: (preferences: ProfilePreferences) => void;
  onSave: () => void | Promise<void>;
  lastSavedAt: string | null;
  saveError: string | null;
}

export default function CoachingDirectivesCard({
  preferences,
  onChange,
  onSave,
  lastSavedAt,
  saveError,
}: CoachingDirectivesCardProps) {
  function update(next: Partial<ProfilePreferences>) {
    onChange({ ...preferences, ...next });
  }

  function toggleEquipment(item: EquipmentOption) {
    update({
      equipment: preferences.equipment.includes(item)
        ? preferences.equipment.filter((existing) => existing !== item)
        : [...preferences.equipment, item],
    });
  }

  function toggleLimitation(item: LimitationOption) {
    if (item === "None") {
      update({ limitations: ["None"] });
      return;
    }

    const withoutNone = preferences.limitations.filter((existing) => existing !== "None");
    const next = withoutNone.includes(item)
      ? withoutNone.filter((existing) => existing !== item)
      : [...withoutNone, item];
    update({ limitations: normalizeLimitations(next) });
  }

  return (
    <Card className="p-4 border-brand-green/30 relative overflow-hidden">
      <div className="absolute inset-0 bg-brand-green/5 pointer-events-none" />
      <div className="relative z-10">
        <div className="flex items-center gap-1.5 mb-4">
          <Sparkles size={16} className="text-brand-green" />
          <h3 className="text-sm font-semibold text-brand-green">
            AI Coaching Directives
          </h3>
        </div>
        <p className="text-xs text-slate-400 mb-5">
          Structured parameters for future workout recommendations. Saved to
          your local backend profile.
        </p>

        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="profile-focus"
                className="block text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1.5"
              >
                Primary Focus
              </label>
              <select
                id="profile-focus"
                value={preferences.focus}
                onChange={(event) =>
                  update({ focus: event.target.value as TrainingFocus })
                }
                className="w-full bg-dashboard border border-cardBorder text-slate-200 text-xs rounded-lg px-2 py-2 focus:outline-none focus:border-brand-green"
              >
                {FOCUS_OPTIONS.map((focus) => (
                  <option key={focus}>{focus}</option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor="profile-frequency"
                className="block text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1.5"
              >
                Frequency
              </label>
              <select
                id="profile-frequency"
                value={preferences.frequency}
                onChange={(event) =>
                  update({ frequency: event.target.value as TrainingFrequency })
                }
                className="w-full bg-dashboard border border-cardBorder text-slate-200 text-xs rounded-lg px-2 py-2 focus:outline-none focus:border-brand-green"
              >
                {FREQUENCY_OPTIONS.map((frequency) => (
                  <option key={frequency}>{frequency}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1.5">
              Typical Max Duration
            </label>
            <div className="flex bg-dashboard border border-cardBorder rounded-lg p-1">
              {DURATION_OPTIONS.map((duration) => (
                <button
                  key={duration}
                  type="button"
                  onClick={() => update({ duration: duration as TrainingDuration })}
                  className={`flex-1 py-1.5 text-[10px] font-medium rounded-md transition-colors ${
                    preferences.duration === duration
                      ? "bg-cardBorder text-white shadow-sm"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {duration}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-2">
              Available Equipment
            </label>
            <div className="flex flex-wrap gap-2">
              {EQUIPMENT_OPTIONS.map((item) => {
                const isSelected = preferences.equipment.includes(item);
                return (
                  <button
                    key={item}
                    type="button"
                    onClick={() => toggleEquipment(item)}
                    className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-[10px] font-medium transition-colors border ${
                      isSelected
                        ? "bg-brand-green/20 border-brand-green/50 text-brand-green"
                        : "bg-dashboard border-cardBorder text-slate-400 hover:border-slate-600"
                    }`}
                  >
                    {isSelected && <Check size={10} />}
                    {item}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label className="block text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-2">
              Limitations & Injuries
            </label>
            <div className="flex flex-wrap gap-2">
              {LIMITATION_OPTIONS.map((item) => {
                const isSelected = preferences.limitations.includes(item);
                return (
                  <button
                    key={item}
                    type="button"
                    onClick={() => toggleLimitation(item)}
                    className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-[10px] font-medium transition-colors border ${
                      isSelected
                        ? item === "None"
                          ? "bg-slate-700 border-slate-500 text-white"
                          : "bg-brand-red/20 border-brand-red/50 text-brand-red"
                        : "bg-dashboard border-cardBorder text-slate-400 hover:border-slate-600"
                    }`}
                  >
                    {isSelected && <Check size={10} />}
                    {item}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <button
              type="button"
              onClick={onSave}
              className="w-full py-2.5 bg-brand-green/10 text-brand-green font-semibold rounded-lg text-sm hover:bg-brand-green/20 transition-colors"
            >
              Save profile
            </button>
            {lastSavedAt && !saveError && (
              <p className="mt-2 text-[11px] text-slate-500">
                Saved {new Date(lastSavedAt).toLocaleTimeString()}
              </p>
            )}
            {saveError && (
              <p className="mt-2 text-[11px] text-brand-red">{saveError}</p>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
