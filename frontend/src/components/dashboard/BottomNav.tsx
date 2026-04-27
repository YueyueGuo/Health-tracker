import { NavLink } from "react-router-dom";
import { Home, History, PlusCircle, LineChart, User } from "lucide-react";
import type { ComponentType } from "react";

interface Item {
  to: string;
  label: string;
  icon: ComponentType<{ size?: number }>;
  end?: boolean;
}

const ITEMS: Item[] = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/history", label: "History", icon: History },
  { to: "/record", label: "Record", icon: PlusCircle },
  { to: "/training", label: "Trends", icon: LineChart },
  { to: "/settings", label: "Profile", icon: User },
];

export function BottomNav() {
  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-50 bg-dashboard/90 backdrop-blur-lg border-t border-cardBorder"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="max-w-2xl mx-auto px-6 h-16 flex items-center justify-between">
        {ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex flex-col items-center gap-1 transition-colors ${
                isActive
                  ? "text-brand-green"
                  : "text-slate-500 hover:text-slate-300"
              }`
            }
          >
            <Icon size={20} />
            <span className="text-[10px] font-medium">{label}</span>
          </NavLink>
        ))}
      </div>
    </div>
  );
}
