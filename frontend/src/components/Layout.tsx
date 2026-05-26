import { NavLink, Outlet } from "react-router-dom";

const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/history", label: "History" },
  { to: "/record", label: "Record" },
  { to: "/training", label: "Trends" },
  { to: "/ask", label: "Ask AI" },
  { to: "/profile", label: "Profile" },
  { to: "/settings", label: "Settings" },
];

export default function Layout() {
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
      </nav>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
