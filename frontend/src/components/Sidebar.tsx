import { NavLink } from "react-router-dom";
import { Logo } from "../site/Logo";
import { Icon } from "./Icon";

const NAV = [
  { section: "Support" },
  { to: "/admin", label: "Dashboard", icon: "dashboard", end: true },
  { to: "/admin/inbox", label: "Live inbox", icon: "chat", badge: "inbox" },
  { to: "/admin/cases", label: "Cases", icon: "folder" },
  { to: "/admin/support", label: "Test the assistant", icon: "support" },
  { section: "Knowledge" },
  { to: "/admin/knowledge", label: "Help articles", icon: "book" },
  { to: "/admin/candidates", label: "Review queue", icon: "sparkle", badge: "candidates" },
  { to: "/admin/emerging", label: "Trending problems", icon: "radar", badge: "emerging" },
  { to: "/admin/intents", label: "Issue types", icon: "tag" },
  { section: "Insights" },
  { to: "/admin/analytics", label: "Reports", icon: "chart" },
  { to: "/admin/settings", label: "Settings", icon: "settings" },
] as const;

export function Sidebar({ open, onNavigate, badges }: { open: boolean; onNavigate: () => void; badges: Record<string, number> }) {
  return (
    <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Main navigation">
      <NavLink to="/admin" className="brand" onClick={onNavigate}>
        <Logo size={30} />
        <span>
          <span className="brand-name">Support IQ</span><br />
          <span className="brand-sub">Agent workspace</span>
        </span>
      </NavLink>
      {NAV.map((item, i) =>
        "section" in item ? (
          <div key={i} className="nav-section">{item.section}</div>
        ) : (
          <NavLink key={item.to} to={item.to} end={"end" in item ? item.end : false} onClick={onNavigate}
            className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            <Icon name={item.icon} size={16} />
            <span>{item.label}</span>
            {"badge" in item && badges[item.badge] > 0 && <span className="nav-badge">{badges[item.badge]}</span>}
          </NavLink>
        ),
      )}
      <NavLink to="/" className="nav-link" style={{ marginTop: "auto" }} onClick={onNavigate}>
        <Icon name="globe" size={16} /><span>View customer site</span>
      </NavLink>
    </aside>
  );
}
