import { Link } from "react-router-dom";
import { Settings, User } from "lucide-react";

interface ProfileHeaderProps {
  displayName: string;
  email: string;
  onChange: (patch: { displayName?: string; email?: string }) => void;
  onSave: () => void | Promise<void>;
  lastSavedAt: string | null;
  saveError: string | null;
}

export default function ProfileHeader({
  displayName,
  email,
  onChange,
  onSave,
  lastSavedAt,
  saveError,
}: ProfileHeaderProps) {
  return (
    <>
      <div className="px-1 mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white tracking-tight">Profile</h1>
        <Link
          to="/settings"
          aria-label="Open settings"
          className="p-2 text-slate-400 hover:text-white transition-colors bg-cardBorder/30 rounded-full no-underline hover:no-underline"
        >
          <Settings size={16} />
        </Link>
      </div>

      <div className="flex items-center gap-4 px-1 mb-6">
        <div className="w-16 h-16 rounded-full bg-gradient-to-tr from-brand-green to-emerald-700 p-[2px]">
          <div className="w-full h-full rounded-full bg-card flex items-center justify-center">
            <User size={32} className="text-slate-300" />
          </div>
        </div>
        <div className="flex-1 min-w-0">
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label
                htmlFor="profile-display-name"
                className="block text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1"
              >
                Name
              </label>
              <input
                id="profile-display-name"
                type="text"
                value={displayName}
                onChange={(event) =>
                  onChange({ displayName: event.target.value })
                }
                placeholder="Your name"
                className="w-full bg-dashboard border border-cardBorder text-slate-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-brand-green"
              />
            </div>
            <div>
              <label
                htmlFor="profile-email"
                className="block text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1"
              >
                Email
              </label>
              <input
                id="profile-email"
                type="email"
                value={email}
                onChange={(event) => onChange({ email: event.target.value })}
                placeholder="you@example.com"
                className="w-full bg-dashboard border border-cardBorder text-slate-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-brand-green"
              />
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onSave}
              className="px-3 py-1.5 bg-brand-green/10 text-brand-green font-semibold rounded-lg text-xs hover:bg-brand-green/20 transition-colors"
            >
              Save identity
            </button>
            {lastSavedAt && !saveError && (
              <span className="text-[11px] text-slate-500">
                Saved {new Date(lastSavedAt).toLocaleTimeString()}
              </span>
            )}
            {saveError && (
              <span className="text-[11px] text-brand-red">{saveError}</span>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
