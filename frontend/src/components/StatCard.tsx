import { Icon } from "./Icon";

export function StatCard({ label, value, icon, hint, accent }: { label: string; value: string; icon: string; hint?: string; accent?: boolean }) {
  return (
    <div className={`stat-card ${accent ? "accent" : ""}`}>
      <span className="stat-icon"><Icon name={icon} /></span>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint" style={accent ? { color: "rgba(255,244,225,.7)" } : undefined}>{hint}</div>}
    </div>
  );
}
