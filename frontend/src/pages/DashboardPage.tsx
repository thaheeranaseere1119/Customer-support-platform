import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { StatusBadge } from "../components/Badges";
import { StackedBarChart } from "../components/Charts";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { api } from "../services/api";
import { caseStatusLabel, num, pct, timeAgo } from "../utils/format";

export const STATUS_SERIES = [
  { key: "known", label: "High confidence", color: "#2E8B5E" },
  { key: "uncertain", label: "Medium confidence", color: "#D98A1C" },
  { key: "unknown", label: "Low confidence", color: "#D9473D" },
];

function Attention({ to, value, label, hint }: { to: string; value: number; label: string; hint: string }) {
  return (
    <Link to={to} className={`stat-card clickable ${value > 0 ? "alert" : ""}`}>
      <div className="stat-value">{num(value)}</div>
      <div className="stat-label" style={{ color: "var(--text)", fontWeight: 600 }}>{label}</div>
      <div className="stat-hint">{hint}</div>
    </Link>
  );
}

export function DashboardPage() {
  const q = useQuery({ queryKey: ["analytics"], queryFn: api.analytics, refetchInterval: 20000 });
  const waiting = useQuery({ queryKey: ["inbox", "badge"], queryFn: () => api.inbox({ handoff_status: "needs_agent" }), refetchInterval: 5000 });
  if (q.isLoading) return <LoadingState label="Loading dashboard…" />;
  if (q.error || !q.data) return <ErrorState message={(q.error as Error)?.message ?? "Dashboard unavailable"} onRetry={() => q.refetch()} />;
  const d = q.data;
  const s = d.stats;
  const waitingCount = waiting.data?.counts.needs_agent ?? 0;
  return (
    <div className="stack" style={{ gap: 20 }}>
      <section aria-labelledby="attention-title">
        <h2 id="attention-title" className="card-title" style={{ marginBottom: 10 }}>Needs attention</h2>
        <div className="attention">
          <Attention to="/admin/inbox" value={waitingCount} label="Customers waiting for an agent" hint={waitingCount ? "Open the live inbox to reply" : "No one is waiting"} />
          <Attention to="/admin/candidates" value={s.pending_candidates} label="Fixes to review" hint="Confirmed by customers, not yet published" />
          <Attention to="/admin/cases" value={d.case_status_counts.escalated ?? 0} label="Escalated cases" hint="Assistant couldn't solve after 3 tries" />
          <Attention to="/admin/emerging" value={s.emerging_open} label="Trending problems" hint="New issues reported by several customers" />
        </div>
      </section>

      <section className="grid grid-5" aria-label="Key numbers">
        <div className="stat-card"><div className="stat-value">{num(s.total_tickets)}</div><div className="stat-label">Requests handled</div></div>
        <div className="stat-card"><div className="stat-value">{num(s.resolved_cases)}</div><div className="stat-label">Solved</div></div>
        <div className="stat-card"><div className="stat-value">{num(s.unknown_issues)}</div><div className="stat-label">New, unrecognised issues</div></div>
        <div className="stat-card"><div className="stat-value">{num(s.knowledge_articles)}</div><div className="stat-label">Published help articles</div></div>
        <div className="stat-card"><div className="stat-value">{pct(s.resolution_success_rate)}</div><div className="stat-label">Solved on customer feedback</div></div>
      </section>

      <div className="dash-grid">
        <section className="card">
          <div className="card-header"><h2 className="card-title">Recent cases</h2><Link to="/admin/cases" className="small">View all</Link></div>
          {d.recent_cases.length === 0 ? <p className="small muted">No cases yet. They appear here as customers chat.</p> : (
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Case</th><th>Problem</th><th>Confidence</th><th>Status</th><th>When</th></tr></thead>
              <tbody>{d.recent_cases.map((c) => (
                <tr key={c.case_id}>
                  <td className="mono"><Link to={`/admin/cases/${c.case_id}`}>{c.case_id}</Link></td>
                  <td style={{ minWidth: 200 }}><span className="clamp-2">{c.complaint}</span></td>
                  <td><StatusBadge status={c.evidence_status} /></td>
                  <td className="small">{caseStatusLabel(c.status)}</td>
                  <td className="small muted" title={c.created_at ?? ""}>{timeAgo(c.created_at)}</td>
                </tr>))}</tbody>
            </table></div>
          )}
        </section>
        <div className="stack">
          <section className="card">
            <div className="card-header"><h2 className="card-title">Cases over the last 14 days</h2></div>
            <StackedBarChart data={d.activity} series={STATUS_SERIES} xKey="date" />
          </section>
          <section className="card">
            <div className="card-header"><h2 className="card-title">Trending problems</h2><Link to="/admin/emerging" className="small">Review</Link></div>
            <ul className="list-plain">
              {d.emerging_issues.map((i) => (
                <li key={i.id}><Link to="/admin/emerging"><span>{i.pattern_name}</span><span className="sub">{num(i.occurrences)} reports</span></Link></li>))}
              {d.emerging_issues.length === 0 && <li><span className="row-item small muted">Nothing trending right now.</span></li>}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
