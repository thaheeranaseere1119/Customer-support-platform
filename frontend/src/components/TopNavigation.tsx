import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { initials, useAgentName } from "../hooks/useAgentName";
import { setStaffToken } from "../hooks/useStaffSession";
import { api } from "../services/api";
import type { Health } from "../types/api";
import { cleanTitle } from "../site/articles";
import { Icon } from "./Icon";

const TITLES: Record<string, [string, string]> = {
  "/": ["Dashboard", "What needs attention today"],
  "/inbox": ["Live inbox", "Customer chats and handoffs"],
  "/support": ["Test the assistant", "Try a complaint and see how the assistant answers"],
  "/cases": ["Cases", "Every request, attempt and customer response"],
  "/knowledge": ["Help articles", "Articles the assistant and customers use"],
  "/candidates": ["Review queue", "Fixes customers confirmed, waiting for review"],
  "/emerging": ["Trending problems", "Similar new issues reported by several customers"],
  "/intents": ["Issue types", "How customer problems are categorised"],
  "/analytics": ["Reports", "Resolution performance and quality checks"],
  "/settings": ["Settings", "Assistant behaviour and your profile"],
};

function AdminSearch() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const q = query.trim().toLowerCase();
  const active = open && q.length >= 2;
  const cases = useQuery({ queryKey: ["search-cases"], queryFn: () => api.cases({ limit: 100 }), enabled: active, staleTime: 30_000 });
  const chats = useQuery({ queryKey: ["inbox", "search"], queryFn: () => api.inbox(), enabled: active, staleTime: 15_000 });
  const articles = useQuery({ queryKey: ["search-articles"], queryFn: () => api.knowledge({ page_size: 100 }), enabled: active, staleTime: 60_000 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) { e.preventDefault(); input.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const results = useMemo(() => {
    if (!active) return null;
    return {
      cases: (cases.data?.items ?? []).filter((c) => c.case_id.toLowerCase().includes(q) || c.complaint.toLowerCase().includes(q)).slice(0, 5),
      chats: (chats.data?.items ?? []).filter((c) => c.customer_name.toLowerCase().includes(q) || c.session_id.includes(q)).slice(0, 4),
      articles: (articles.data?.items ?? []).filter((a) => a.article_id.toLowerCase().includes(q) || a.title.toLowerCase().includes(q)).slice(0, 5),
    };
  }, [active, q, cases.data, chats.data, articles.data]);
  const first = results && (results.chats[0] ? `/admin/inbox?chat=${results.chats[0].session_id}`
    : results.cases[0] ? `/admin/cases/${results.cases[0].case_id}`
      : results.articles[0] ? `/admin/knowledge?article=${results.articles[0].article_id}` : null);
  const go = (to: string) => { navigate(to); setOpen(false); setQuery(""); input.current?.blur(); };
  const loading = cases.isLoading || chats.isLoading || articles.isLoading;
  const empty = results && !results.cases.length && !results.chats.length && !results.articles.length;

  return (
    <div className="admin-search" role="search">
      <Icon name="search" size={15} />
      <label htmlFor="admin-search" className="sr-only">Search cases, customers and articles</label>
      <input id="admin-search" ref={input} value={query} placeholder="Search cases, customers, articles…" autoComplete="off"
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => { if (e.key === "Escape") { setOpen(false); input.current?.blur(); } if (e.key === "Enter" && first) go(first); }} />
      {results && (
        <div className="admin-search-results" role="listbox" aria-label="Search results">
          {results.chats.length > 0 && <h5>Customers</h5>}
          {results.chats.map((c) => <Link key={c.session_id} to={`/admin/inbox?chat=${c.session_id}`} onClick={() => go(`/admin/inbox?chat=${c.session_id}`)}>{c.customer_name}<small>{c.last_message.slice(0, 50)}</small></Link>)}
          {results.cases.length > 0 && <h5>Cases</h5>}
          {results.cases.map((c) => <Link key={c.case_id} to={`/admin/cases/${c.case_id}`} onClick={() => go(`/admin/cases/${c.case_id}`)}>{c.case_id}<small>{c.complaint.slice(0, 50)}</small></Link>)}
          {results.articles.length > 0 && <h5>Help articles</h5>}
          {results.articles.map((a) => <Link key={a.article_id} to={`/admin/knowledge?article=${a.article_id}`} onClick={() => go(`/admin/knowledge?article=${a.article_id}`)}>{cleanTitle(a.title)}<small>{a.article_id}</small></Link>)}
          {loading && empty && <p>Searching…</p>}
          {!loading && empty && <p>No matches for “{query.trim()}”.</p>}
        </div>
      )}
    </div>
  );
}

function AgentMenu() {
  const [name, setName] = useAgentName();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  if (editing) {
    return (
      <form className="row" onSubmit={(e) => { e.preventDefault(); setName(draft); setEditing(false); }}>
        <label htmlFor="agent-display-name" className="sr-only">Your name</label>
        <input id="agent-display-name" className="input" style={{ width: 160, padding: "5px 8px" }} value={draft} maxLength={80}
          onChange={(e) => setDraft(e.target.value)} autoFocus />
        <button type="submit" className="btn btn-primary btn-sm">Save</button>
      </form>
    );
  }
  return (
    <div className="row" style={{ gap: 6 }}>
      <button type="button" className="agent-chip" onClick={() => { setDraft(name); setEditing(true); }} title="Change the name customers see on your replies">
        <span className="avatar" aria-hidden="true">{initials(name)}</span><span className="agent-name">{name}</span>
      </button>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setStaffToken(null)}>Sign out</button>
    </div>
  );
}

export function TopNavigation({ health, healthError, onMenu, waiting = 0 }:
  { health?: Health; healthError: boolean; onMenu: () => void; waiting?: number }) {
  const { pathname } = useLocation();
  const key = "/" + (pathname.replace(/^\/admin/, "").split("/")[1] || "");
  const [title, sub] = TITLES[key] ?? ["Support IQ", ""];
  useEffect(() => { document.title = `${waiting > 0 ? `(${waiting}) ` : ""}${title} · Support IQ Admin`; }, [title, waiting]);
  const color = healthError ? "var(--status-unknown)" : health?.status === "ok" ? "var(--status-known)" : "var(--status-uncertain)";
  const healthLabel = healthError ? "System offline" : health ? (health.status === "ok" ? "All systems normal" : "Running with reduced features") : "Checking…";
  return (
    <header className="topnav">
      <button type="button" className="btn btn-ghost icon-btn menu-button" onClick={onMenu} aria-label="Open navigation"><Icon name="menu" /></button>
      <div style={{ minWidth: 0 }}>
        <div className="topnav-title">{title}</div>
        <div className="topnav-sub">{sub}</div>
      </div>
      <AdminSearch />
      <div className="topnav-right">
        <span className="health-pill" title={healthLabel}><span className="health-dot" style={{ background: color }} />{healthLabel}</span>
        <AgentMenu />
      </div>
    </header>
  );
}
