import { ChevronRight, Footprints } from "lucide-react";
import { Link } from "react-router-dom";
import { Card } from "../ui/Card";
import { useShoesList } from "../../hooks/useShoes";

/**
 * Settings → Gear card. Single "Shoes" row that links to `/shoes`,
 * mirroring the count summary that `ShoesSettingsCard` exposes today.
 */
export default function GearCard() {
  const { data: shoes, loading } = useShoesList("active");
  const count = shoes?.length ?? 0;

  const summary = loading ? "Loading…" : `${count} active`;

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-4">
        <Footprints size={16} className="text-slate-300" />
        <h3 className="text-sm font-semibold text-slate-200">Gear</h3>
      </div>

      <Link
        to="/shoes"
        className="flex items-center justify-between gap-3 p-3 rounded-lg bg-dashboard/40 border border-cardBorder/40 text-slate-200 hover:bg-cardBorder/20 transition-colors no-underline hover:no-underline"
      >
        <div className="min-w-0">
          <div className="text-sm font-medium text-slate-200">Shoes</div>
          <div className="text-[11px] text-slate-500">{summary}</div>
        </div>
        <ChevronRight size={16} className="text-slate-500" />
      </Link>
    </Card>
  );
}
