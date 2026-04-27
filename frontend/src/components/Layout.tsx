import { NavLink, Outlet } from "react-router-dom";
import { useUnits } from "../hooks/useUnits";

const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/history", label: "History" },
  { to: "/record", label: "Record" },
  { to: "/sleep", label: "Sleep" },
  { to: "/recovery", label: "Recovery" },
  { to: "/training", label: "Training Load" },
  { to: "/ask", label: "Ask AI" },
];

export default function Layout() {
  const { units, setUnits } = useUnits();
  return (
    <div className="app-layout">
      <nav className="sidebar">
        <h1>Health Tracker</h1>
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => (isActive ? "active" : "")}
            end={item.to === "/"}
          >
            {item.label}
          </NavLink>
        ))}
        <div className="sidebar-footer">
          <div className="units-toggle" role="group" aria-label="Units">
            <button
              type="button"
              className={units === "imperial" ? "active" : ""}
              onClick={() => setUnits("imperial")}
              title="Miles, feet, °F, mph"
            >
              mi
            </button>
            <button
              type="button"
              className={units === "metric" ? "active" : ""}
              onClick={() => setUnits("metric")}
              title="Kilometers, meters, °C, m/s"
            >
              km
            </button>
          </div>
        </div>
      </nav>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
