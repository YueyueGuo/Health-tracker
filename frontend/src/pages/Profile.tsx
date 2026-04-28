import CoachingDirectivesCard from "../components/profile/CoachingDirectivesCard";
import DataSourcesCard from "../components/profile/DataSourcesCard";
import PhysiologyVitalsCard from "../components/profile/PhysiologyVitalsCard";
import ProfileHeader from "../components/profile/ProfileHeader";
import { useProfilePreferences } from "../hooks/useProfilePreferences";

export default function Profile() {
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
      <div className="loading" style={{ marginTop: "1rem" }}>
        Loading profile...
      </div>
    );
  }

  return (
    <div className="pb-2 pt-4">
      <ProfileHeader
        displayName={preferences.displayName}
        email={preferences.email}
        onChange={(patch) => setPreferences({ ...preferences, ...patch })}
        onSave={() => void save(preferences)}
        lastSavedAt={lastSavedAt}
        saveError={saveError}
      />

      <div className="space-y-4">
        <CoachingDirectivesCard
          preferences={preferences}
          onChange={setPreferences}
          onSave={() => void save(preferences)}
          lastSavedAt={lastSavedAt}
          saveError={saveError}
        />
        <PhysiologyVitalsCard
          vitals={preferences.vitals}
          onChange={(vitals) => setPreferences({ ...preferences, vitals })}
        />
        <DataSourcesCard />
      </div>
    </div>
  );
}
