import type { KnowledgeArticle } from "../types/api";
import { humanize, timeAgo } from "../utils/format";

const STATUS_CLASS = { ACTIVE: "badge-known", DRAFT: "badge-uncertain", ARCHIVED: "badge-neutral" } as const;

export function KnowledgeTable({ items, onOpen }: { items: KnowledgeArticle[]; onOpen: (a: KnowledgeArticle) => void }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>ID</th><th>Title</th><th>Category</th><th>Intent</th><th>Version</th><th>Status</th><th>Source</th><th>Updated</th></tr></thead>
        <tbody>
          {items.map((a) => (
            <tr key={a.id} className="clickable" onClick={() => onOpen(a)} tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") onOpen(a); }}>
              <td className="mono"><b>{a.article_id}</b></td>
              <td style={{ minWidth: 220 }}><b>{a.title}</b><div className="tiny muted clamp-2">{a.content.split("\n")[0]}</div></td>
              <td>{a.category}</td>
              <td className="small">{a.source === "synthetic_demo_kb_general" ? <span className="badge badge-info">General guidance</span> : humanize(a.intent)}</td>
              <td>v{a.version}</td>
              <td><span className={`badge ${STATUS_CLASS[a.status]}`}>{a.status}</span></td>
              <td className="tiny">{humanize(a.source)}</td>
              <td className="tiny muted">{timeAgo(a.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
