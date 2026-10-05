import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AssistantResolution } from "../components/AssistantResolution";
import { StatusBadge } from "../components/Badges";
import { ErrorState } from "../components/ErrorState";
import { Icon } from "../components/Icon";
import { LoadingState } from "../components/LoadingState";
import { MemoryPanel } from "../components/MemoryPanel";
import { useAgentName } from "../hooks/useAgentName";
import { useToast } from "../hooks/useToast";
import { api } from "../services/api";
import type { HandoffStatus } from "../types/api";
import { caseStatusLabel, timeAgo } from "../utils/format";

export const HANDOFF_LABEL: Record<HandoffStatus, string> = {
  needs_agent: "Waiting for agent", agent: "With an agent", bot: "Assistant handling", closed: "Closed",
};
const HANDOFF_CLASS: Record<HandoffStatus, string> = {
  needs_agent: "badge-unknown", agent: "badge-yellow", bot: "badge-neutral", closed: "badge-neutral",
};
const FILTERS: [string, string][] = [["", "All"], ["needs_agent", "Waiting"], ["agent", "With an agent"], ["bot", "Assistant"], ["closed", "Closed"]];

/** Reply templates. They only insert text into the reply box; the agent edits and sends as usual. */
const CANNED: { title: string; text: (customer: string, agent: string) => string }[] = [
  { title: "Greeting", text: (c, a) => `Hi ${c}, this is ${a} from the support team. I've read through your chat and I'm looking into this now.` },
  { title: "Need more details", text: (c) => `Thanks ${c}. Could you tell me the make and model of your device, and roughly when the problem started?` },
  { title: "Checking", text: () => "Thanks for waiting. I'm checking this with our systems now and will update you here in a few minutes." },
  { title: "Restart steps", text: () => "Could you try restarting the device (and the router, if this is about home internet), then let me know if anything changes?" },
  { title: "Escalated", text: () => "I've passed this to our specialist team with all the details from this chat. They'll follow up with you here." },
  { title: "Solved, closing", text: (c) => `Glad that's sorted, ${c}! I'll close this chat now. If anything else comes up, just send us a message.` },
];

function Transcript({ sessionId, onBack }: { sessionId: string; onBack: () => void }) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [agent] = useAgentName();
  const [text, setText] = useState("");
  const [canned, setCanned] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const reply = useRef<HTMLTextAreaElement>(null);
  const conv = useQuery({ queryKey: ["conversation", sessionId], queryFn: () => api.conversation(sessionId), refetchInterval: 3000 });
  const data = conv.data;
  const count = data?.messages.length ?? 0;
  useEffect(() => { const el = list.current; if (el) el.scrollTo?.({ top: el.scrollHeight }); }, [count]);
  useEffect(() => { if (data && data.agent_unread > 0) api.markRead(sessionId).then(() => qc.invalidateQueries({ queryKey: ["inbox"] })); },
    [data, sessionId, qc]);

  const refresh = (c: unknown) => { qc.setQueryData(["conversation", sessionId], c); qc.invalidateQueries({ queryKey: ["inbox"] }); };
  const act = useMutation({
    mutationFn: (body: { action: "take" | "release" | "close"; resolved?: boolean }) => api.handoff(sessionId, { ...body, agent }),
    onSuccess: refresh, onError: (e: Error) => notify(e.message, "error"),
  });
  const send = useMutation({
    mutationFn: (message: string) => api.agentMessage(sessionId, agent, message),
    onSuccess: (c) => { refresh(c); setText(""); }, onError: (e: Error) => notify(e.message, "error"),
  });

  if (conv.isLoading) return <LoadingState label="Loading conversation…" />;
  if (conv.error || !data) return <ErrorState message={(conv.error as Error)?.message ?? "Conversation not found"} onRetry={() => conv.refetch()} />;
  const status = data.handoff_status;
  const mine = status === "agent" && data.assigned_agent === agent;
  const submit = (e: FormEvent) => { e.preventDefault(); if (text.trim()) send.mutate(text.trim()); };
  const firstSeen = data.messages[0]?.created_at ?? data.created_at;

  return (
    <div className="inbox-detail">
      <section className="card inbox-chat">
        <button type="button" className="btn btn-ghost btn-sm inbox-back" onClick={onBack}>← All chats</button>
        <div className="card-header">
          <div>
            <h2 className="card-title" style={{ fontSize: 18 }}>{data.customer_name}</h2>
            <div className="row" style={{ marginTop: 4 }}>
              <span className={`badge ${HANDOFF_CLASS[status]}`}>{HANDOFF_LABEL[status]}</span>
              {status === "agent" && <span className="small muted">Assigned to {mine ? "you" : data.assigned_agent}</span>}
              {status === "needs_agent" && data.handoff_reason && <span className="small muted">{data.handoff_reason}</span>}
            </div>
          </div>
          <div className="row">
            {!mine && <button type="button" className="btn btn-primary btn-sm" disabled={act.isPending} onClick={() => act.mutate({ action: "take" })}>Assign to me</button>}
            {status === "agent" && <button type="button" className="btn btn-ghost btn-sm" disabled={act.isPending} onClick={() => act.mutate({ action: "release" })}>Hand back to assistant</button>}
            {status !== "closed" && <button type="button" className="btn btn-ghost btn-sm" disabled={act.isPending} onClick={() => act.mutate({ action: "close", resolved: true })}><Icon name="check" size={14} />Mark solved & close</button>}
          </div>
        </div>
        <div className="chat inbox-transcript" ref={list}>
          {data.messages.map((m) => {
            const caseId = m.metadata.case_id as string | undefined;
            const attempt = Number(m.metadata.attempt ?? 1);
            const rich = m.role === "assistant" && !!caseId;
            if (m.role === "system") return <div key={m.id} className="bubble system">{m.message}</div>;
            return (
              <div key={m.id} className={`bubble ${m.role === "user" ? "user-left" : m.role === "agent" ? "agent-right" : "assistant"} ${rich ? "rich" : ""}`}>
                <div className="tiny" style={{ fontWeight: 600, marginBottom: 4 }}>
                  {m.role === "user" ? data.customer_name : m.role === "agent" ? String(m.metadata.agent ?? "Agent") : "Assistant"}</div>
                {rich ? m.message.split("\n")[0] : m.message}
                {rich && <AssistantResolution caseId={caseId!} attempt={attempt} sessionId={sessionId} audience="admin" interactive={false} />}
                <div className="bubble-meta" title={m.created_at}>{timeAgo(m.created_at)}</div>
              </div>
            );
          })}
        </div>
        <form className="stack-sm section-gap" onSubmit={submit}>
          <label htmlFor="agent-reply" className="sr-only">Reply</label>
          <textarea id="agent-reply" ref={reply} className="textarea" style={{ minHeight: 70 }} value={text} maxLength={2000}
            placeholder={mine ? `Reply to ${data.customer_name}…` : `Reply to ${data.customer_name} (this assigns the chat to you)…`}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e); }} />
          <div className="row">
            <div className="canned">
              <button type="button" className="btn btn-ghost btn-sm" aria-expanded={canned} onClick={() => setCanned((v) => !v)}>Canned replies</button>
              {canned && (
                <div className="canned-menu" role="menu">
                  {CANNED.map((c) => (
                    <button key={c.title} type="button" role="menuitem" onClick={() => { setText(c.text(data.customer_name, agent)); setCanned(false); reply.current?.focus(); }}>
                      <b>{c.title}</b>{c.text(data.customer_name, agent).slice(0, 70)}…</button>))}
                </div>
              )}
            </div>
            <span className="tiny muted">Replying as <b>{agent}</b> · <span className="kbd">⌘</span> <span className="kbd">Enter</span> to send</span>
            <span className="spacer" />
            <button type="submit" className="btn btn-primary" disabled={!text.trim() || send.isPending}><Icon name="send" size={14} />Send</button>
          </div>
        </form>
      </section>
      <div className="stack">
        <section className="card customer-card" aria-label="Customer details">
          <div className="card-header"><h3 className="card-title">Customer</h3></div>
          <dl>
            <dt>Name</dt><dd>{data.customer_name}</dd>
            <dt>Channel</dt><dd>{data.channel === "customer_app" ? "Website chat" : "Agent console"}</dd>
            <dt>Started</dt><dd title={firstSeen ?? ""}>{timeAgo(firstSeen)}</dd>
            <dt>Requests</dt><dd>{data.cases.length}</dd>
          </dl>
        </section>
        <section className="card">
          <div className="card-header"><h3 className="card-title">Requests in this chat</h3></div>
          <ul className="list-plain">
            {data.cases.length === 0 && <li><span className="row-item small muted">No requests yet.</span></li>}
            {data.cases.map((c) => (
              <li key={c.case_id}><Link to={`/admin/cases/${c.case_id}`}>
                <span className="clamp-2 small">{c.complaint}</span>
                <span className="row" style={{ flexShrink: 0 }}><StatusBadge status={c.evidence_status} /><span className="sub">{caseStatusLabel(c.status)}</span></span>
              </Link></li>))}
          </ul>
        </section>
        <MemoryPanel memory={data.memory} summary={data.memory_summary} />
      </div>
    </div>
  );
}

/** Live inbox: every customer chat, with handoff to a person and agent replies. */
export function InboxPage() {
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState("");
  const selected = params.get("chat");
  const inbox = useQuery({ queryKey: ["inbox", filter], queryFn: () => api.inbox({ handoff_status: filter || undefined }), refetchInterval: 3000 });
  const items = useMemo(() => inbox.data?.items ?? [], [inbox.data]);
  const counts = inbox.data?.counts ?? {};
  const active = selected ?? items[0]?.session_id ?? null;
  const select = (id: string | null) => setParams(id ? { chat: id } : {}, { replace: true });

  // j / k move between conversations (ignored while typing).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || e.metaKey || e.ctrlKey || !items.length) return;
      if (e.key !== "j" && e.key !== "k") return;
      const index = Math.max(0, items.findIndex((c) => c.session_id === active));
      const next = items[Math.min(items.length - 1, Math.max(0, index + (e.key === "j" ? 1 : -1)))];
      if (next) setParams({ chat: next.session_id }, { replace: true });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, active, setParams]);

  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="row">
        <div className="tabs" role="tablist" aria-label="Chat status">
          {FILTERS.map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={filter === key} className={`tab ${filter === key ? "active" : ""}`}
              onClick={() => { setFilter(key); select(null); }}>
              {label} ({key ? counts[key] ?? 0 : Object.values(counts).reduce((a, b) => a + b, 0)})</button>
          ))}
        </div>
        <span className="spacer" />
        <span className="tiny muted"><span className="kbd">j</span> <span className="kbd">k</span> next / previous chat</span>
      </div>
      {inbox.error && <ErrorState message={(inbox.error as Error).message} onRetry={() => inbox.refetch()} />}
      <div className={`inbox-layout ${selected ? "has-selection" : ""}`}>
        <section className="card inbox-list" aria-label="Conversations">
          {inbox.isLoading && <LoadingState rows={5} />}
          {!inbox.isLoading && items.length === 0 && <p className="small muted" style={{ padding: 12 }}>No conversations here. New website chats appear automatically.</p>}
          {items.map((c) => (
            <button key={c.session_id} type="button" className={`inbox-item ${active === c.session_id ? "active" : ""} ${c.agent_unread > 0 ? "unread" : ""}`}
              onClick={() => select(c.session_id)}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <strong>{c.customer_name}</strong>
                <span className="tiny muted" title={c.updated_at ?? ""}>{timeAgo(c.updated_at)}</span>
              </div>
              <div className="small muted clamp-2">{c.last_role === "agent" ? "You: " : c.last_role === "assistant" ? "Assistant: " : ""}{c.last_message}</div>
              <div className="row" style={{ marginTop: 6 }}>
                <span className={`badge ${HANDOFF_CLASS[c.handoff_status]}`}>{HANDOFF_LABEL[c.handoff_status]}</span>
                {c.open_cases > 0 && <span className="tiny muted">{c.open_cases} open</span>}
                {c.agent_unread > 0 && <span className="nav-badge" style={{ marginLeft: "auto" }}>{c.agent_unread}</span>}
              </div>
            </button>
          ))}
        </section>
        {active ? <Transcript key={active} sessionId={active} onBack={() => select(null)} /> : <section className="card empty-state"><p className="muted">Select a conversation.</p></section>}
      </div>
    </div>
  );
}
