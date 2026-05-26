import { User } from "lucide-react";
import { Card } from "../ui/Card";
import { useProfilePreferences } from "../../hooks/useProfilePreferences";

/**
 * Settings → Account card: edit displayName / email / dateOfBirth and
 * PATCH `/api/profile`. Mirrors the ProfileHeader save pattern so
 * persistence stays consistent.
 */
export default function AccountCard() {
  const {
    preferences,
    setPreferences,
    save,
    loading,
    lastSavedAt,
    saveError,
  } = useProfilePreferences();

  if (loading) {
    return (
      <Card className="p-4">
        <div className="text-xs text-slate-500">Loading account…</div>
      </Card>
    );
  }

  function update(patch: Partial<typeof preferences>) {
    setPreferences({ ...preferences, ...patch });
  }

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-4">
        <User size={16} className="text-slate-300" />
        <h3 className="text-sm font-semibold text-slate-200">Account</h3>
      </div>

      <div className="space-y-3">
        <div>
          <label
            htmlFor="account-display-name"
            className="block text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1"
          >
            Name
          </label>
          <input
            id="account-display-name"
            aria-label="Name"
            type="text"
            value={preferences.displayName}
            onChange={(event) => update({ displayName: event.target.value })}
            placeholder="Your name"
            className="w-full bg-dashboard border border-cardBorder text-slate-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-brand-green"
          />
        </div>

        <div>
          <label
            htmlFor="account-email"
            className="block text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1"
          >
            Email
          </label>
          <input
            id="account-email"
            aria-label="Email"
            type="email"
            value={preferences.email}
            onChange={(event) => update({ email: event.target.value })}
            placeholder="you@example.com"
            className="w-full bg-dashboard border border-cardBorder text-slate-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-brand-green"
          />
        </div>

        <div>
          <label
            htmlFor="account-dob"
            className="block text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1"
          >
            Date of birth
          </label>
          <input
            id="account-dob"
            aria-label="Date of birth"
            type="date"
            value={preferences.dateOfBirth}
            onChange={(event) => update({ dateOfBirth: event.target.value })}
            placeholder="Not set"
            className="w-full bg-dashboard border border-cardBorder text-slate-200 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-brand-green"
          />
          <p className="mt-1 text-[11px] text-slate-500">
            {formatDob(preferences.dateOfBirth)}
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void save(preferences)}
          className="px-3 py-1.5 bg-brand-green/10 text-brand-green font-semibold rounded-lg text-xs hover:bg-brand-green/20 transition-colors"
        >
          Save account
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
    </Card>
  );
}

function formatDob(value: string): string {
  if (!value) return "Not set";
  // Expect YYYY-MM-DD; render in en-US "Oct 12, 1993".
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return "Not set";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(parsed);
}
