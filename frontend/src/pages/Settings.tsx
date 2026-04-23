import GoalsSection from "../components/GoalsSection";
import LocationSettingsSection from "../components/settings/LocationSettingsSection";

/**
 * Settings page: manage your saved ``user_locations``.
 *
 * Entry paths mirror the LocationPicker so the UX is consistent:
 *  - Search by name (Open-Meteo geocoding \u2192 pick a candidate).
 *  - Use current device location (``navigator.geolocation``).
 *  - Advanced: enter raw lat/lng (rare \u2014 for pinning exact spots).
 *
 * Additional list affordances: set-default, rename, delete.
 */
export default function Settings() {
  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
        <p>Saved places used to attach base altitude to indoor workouts.</p>
      </div>

      <GoalsSection />
      <LocationSettingsSection />
    </div>
  );
}
