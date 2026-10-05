import type { AnalyticsResponse } from "../types/api";
import { num, pct } from "../utils/format";
import { StatCard } from "./StatCard";

export function AnalyticsCards({ stats }: { stats: AnalyticsResponse["stats"] }) {
  return (
    <div className="grid grid-5">
      <StatCard label="Total Tickets" value={num(stats.total_tickets)} icon="database" hint={`${num(stats.dataset_tickets)} synthetic dataset + ${num(stats.live_cases)} live`} />
      <StatCard label="Resolved Cases" value={num(stats.resolved_cases)} icon="check" hint={`${num(stats.resolved_live_cases)} resolved live`} />
      <StatCard label="Unknown Issues" value={num(stats.unknown_issues)} icon="radar" hint={`${num(stats.uncertain_cases)} uncertain · ${num(stats.emerging_open)} emerging`} />
      <StatCard label="Knowledge Articles" value={num(stats.knowledge_articles)} icon="book" hint={`${num(stats.draft_articles)} draft · ${num(stats.pending_candidates)} candidates`} />
      <StatCard label="Resolution Success Rate" value={pct(stats.resolution_success_rate)} icon="target" accent
        hint={stats.resolution_success_rate === null ? "No feedback collected yet" : `Escalation rate ${pct(stats.escalation_rate)}`} />
    </div>
  );
}
