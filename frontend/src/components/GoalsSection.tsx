import GoalForm from "./settings/GoalForm";
import GoalRow from "./settings/GoalRow";
import { useGoals } from "../hooks/useGoals";

/**
 * Training goals CRUD. Lives above UserLocations on the Settings page.
 * The daily recommendation uses the primary goal (at most one) to
 * periodize its intensity guidance.
 */
export default function GoalsSection() {
  const { goals, error, reload } = useGoals();

  return (
    <>
      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <h2 style={{ marginTop: 0 }}>Add a goal</h2>
        <GoalForm onAdded={reload} />
      </div>

      <div className="card" style={{ padding: 0, marginBottom: 16 }}>
        <h2 style={{ padding: "20px 24px 12px" }}>Goals</h2>
        {error && (
          <div className="error" style={{ margin: "0 24px 12px" }}>
            {error}
          </div>
        )}
        {!goals && <div className="loading">Loading…</div>}
        {goals && goals.length === 0 && (
          <div style={{ padding: "0 24px 20px", color: "var(--text-muted)" }}>
            No goals yet. Add one above so the daily recommendation can
            periodize toward it.
          </div>
        )}
        {goals && goals.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>Race</th>
                <th>Target date</th>
                <th>Weeks away</th>
                <th>Status</th>
                <th>Primary</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {goals.map((g) => (
                <GoalRow key={g.id} goal={g} onChange={reload} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
