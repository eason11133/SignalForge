import { NavLink } from "react-router-dom";
import {
  ChevronLeft,
  ChevronRight,
  Radar,
  Search,
  Settings,
  Rocket,
} from "lucide-react";
import { cn } from "../lib/utils";

const links = [
  { to: "/", icon: Radar, label: "研究工作台" },
  { to: "/research-one", icon: Search, label: "臨時查一個 idea" },
  { to: "/opportunities", icon: Radar, label: "商機工作台" },
  { to: "/execute", icon: Rocket, label: "市場執行與學習" },
  { to: "/system", icon: Settings, label: "系統狀態" },
];

interface Props {
  collapsed: boolean;
  onToggle: () => void;
}

export default function Sidebar({ collapsed, onToggle }: Props) {
  return (
    <aside className={cn("fixed left-0 top-0 h-screen bg-bg-primary border-r border-border-secondary z-40 flex flex-col transition-all duration-200", collapsed ? "w-16" : "w-56")}>
      <div className="flex h-14 items-center gap-3 border-b border-border-secondary px-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-text-primary text-bg-primary"><Radar className="h-4 w-4" /></div>
        {!collapsed && <div className="min-w-0"><div className="truncate text-sm font-semibold tracking-[-0.01em] text-text-primary">SignalForge</div><div className="truncate text-[9px] tracking-[0.06em] text-text-tertiary">先查市場，再決定要不要做</div></div>}
      </div>

      <nav className="flex-1 space-y-1 px-2 py-4" aria-label="主要導覽">
        {links.map((link) => <NavLink key={link.to} to={link.to} end={link.to === "/"} title={collapsed ? link.label : undefined} className={({ isActive }) => cn("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-info/30", isActive ? "bg-text-primary text-bg-primary" : "text-text-secondary hover:bg-bg-secondary hover:text-text-primary")}><link.icon className="h-[18px] w-[18px] shrink-0" />{!collapsed && <span className="truncate">{link.label}</span>}</NavLink>)}
      </nav>

      <button type="button" onClick={onToggle} aria-label={collapsed ? "展開側邊欄" : "收合側邊欄"} className="flex h-11 items-center justify-center border-t border-border-secondary text-text-tertiary transition-colors hover:bg-bg-secondary hover:text-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-info/30">{collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}</button>
    </aside>
  );
}
