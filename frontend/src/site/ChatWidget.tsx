import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { AssistantResolution } from "../components/AssistantResolution";
import { Icon } from "../components/Icon";
import { VoiceButton } from "../components/VoiceButton";
import { useToast } from "../hooks/useToast";
import { ApiError, api } from "../services/api";
import type { ChatMessage, Conversation } from "../types/api";
import { Logo } from "./Logo";

const STORE_KEY = "telecom-customer-chat";
const SEEN_KEY = "telecom-customer-chat-seen";

const read = (key: string): string | null => { try { return window.localStorage.getItem(key); } catch { return null; } };
const write = (key: string, value: string | null) => {
  try { if (value) window.localStorage.setItem(key, value); else window.localStorage.removeItem(key); } catch { /* storage unavailable */ }
};
const time = (iso: string) => new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

const STARTERS = ["My mobile data isn't working", "My broadband keeps dropping", "I was charged twice", "My SIM isn't detected"];
const STATUS_LINE: Record<Conversation["handoff_status"], string> = {
  bot: "Virtual assistant · replies instantly",
  needs_agent: "Finding someone to help you…",
  agent: "Support team",
  closed: "Chat ended · send a message to start again",
};
const REQUEST_STATUS: Record<string, string> = {
  awaiting_feedback: "Waiting for your reply", retry_pending: "Trying another fix", needs_more_info: "Needs more details",
  resolved: "Solved", candidate_submitted: "Solved", escalated: "With our support team", resolved_by_agent: "Solved by our team",
};

/** Plain-language opening line for an assistant answer (the admin console keeps the technical wording). */
export function customerHeadline(message: string, status: unknown, attempt: number): string {
  // Always positive: unknown questions still get the closest guidance, never a "no match" message.
  const first = message.split("\n")[0];
  if (first.startsWith("The evidence is insufficient")) return "Let's narrow this down together. Could you check these for me?";
  if (attempt > 1) return "Here's another approach to try:";
  if (first.includes("BEST-SUITABLE GUIDANCE")) return "Here are the steps that help most with issues like this:";
  if (status === "known") return "Here's what usually fixes this:";
  return "This looks like a familiar issue. These steps should help:";
}

interface OpenOptions { message?: string; human?: boolean; view?: "chat" | "requests" }
interface ChatContextValue { open: (options?: OpenOptions) => void }
const ChatContext = createContext<ChatContextValue>({ open: () => undefined });
export const useChatWidget = () => useContext(ChatContext);

function Bubble({ m, sessionId, latestByCase }: { m: ChatMessage; sessionId: string; latestByCase: Record<string, number> }) {
  const caseId = m.metadata.case_id as string | undefined;
  const attempt = Number(m.metadata.attempt ?? 1);
  // Feedback bookkeeping is for the support team; the customer sees the outcome in the answer itself.
  if (m.role === "system" && m.metadata.feedback) return null;
  if (m.role === "system") return <div className="cw-note">{m.message}</div>;
  const mine = m.role === "user";
  const rich = m.role === "assistant" && !!caseId;
  return (
    <div className={`cw-row ${mine ? "mine" : ""}`}>
      <div className={`cw-bubble ${mine ? "mine" : m.role === "agent" ? "agent" : "bot"} ${rich ? "rich" : ""}`}>
        {m.role === "agent" && <div className="cw-sender">{String(m.metadata.agent ?? "Support team")}</div>}
        <div className="cw-text">{rich ? customerHeadline(m.message, m.metadata.status, attempt) : m.message}</div>
        {rich && <AssistantResolution caseId={caseId!} attempt={attempt} sessionId={sessionId}
          audience="customer" interactive={latestByCase[caseId!] === attempt} />}
        <div className="cw-time">{time(m.created_at)}</div>
      </div>
    </div>
  );
}

function StartForm({ pendingQuestion, busy, onStart }: { pendingQuestion?: string; busy: boolean; onStart: (name: string) => void }) {
  const [name, setName] = useState("");
  return (
    <form className="cw-start" onSubmit={(e) => { e.preventDefault(); onStart(name.trim() || "there"); }}>
      <h3>Hi there</h3>
      <p>Our virtual assistant can help with most phone, internet, SIM and billing problems, and it can bring in a person whenever you like.</p>
      {pendingQuestion && <p className="cw-quote">“{pendingQuestion}”</p>}
      <label htmlFor="cw-name">Your first name</label>
      <input id="cw-name" className="s-input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="e.g. Asha" autoFocus />
      <button type="submit" className="s-btn s-btn-primary" disabled={busy}>{busy ? "Starting…" : "Start chat"}</button>
      <small>For your safety, keep passwords, PINs and card numbers out of chat.</small>
    </form>
  );
}

function ChatBody({ sessionId, conversation, view, setView, onNewChat, pending, clearPending }: {
  sessionId: string; conversation?: Conversation; view: "chat" | "requests"; setView: (v: "chat" | "requests") => void;
  onNewChat: () => void; pending: OpenOptions | null; clearPending: () => void;
}) {
  const qc = useQueryClient();
  const { notify } = useToast();
  const [text, setText] = useState("");
  const body = useRef<HTMLDivElement>(null);
  const thread = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const stick = useRef(true);

  const send = useMutation({
    mutationFn: (message: string) => api.sendMessage(sessionId, message),
    onSuccess: (reply) => qc.setQueryData(["conversation", sessionId], reply.conversation),
    onError: (e: Error) => notify(e.message, "error"),
  });
  const human = useMutation({
    mutationFn: (action: "request" | "cancel") =>
      api.handoff(sessionId, action === "request" ? { action, reason: "Customer asked for a human agent" } : { action }),
    onSuccess: (c) => qc.setQueryData(["conversation", sessionId], c),
    onError: (e: Error) => notify(e.message, "error"),
  });

  // Questions or "talk to a person" requests started from elsewhere on the site.
  useEffect(() => {
    if (!pending || !conversation) return;
    if (pending.message) send.mutate(pending.message);
    if (pending.human && conversation.handoff_status !== "needs_agent" && conversation.handoff_status !== "agent") human.mutate("request");
    clearPending();
  }, [pending, conversation, send, human, clearPending]);

  const status = conversation?.handoff_status ?? "bot";
  const count = conversation?.messages.length ?? 0;
  useEffect(() => { const el = body.current; if (el && stick.current) el.scrollTop = el.scrollHeight; }, [count, send.isPending, view]);
  useEffect(() => {
    const el = body.current;
    const inner = thread.current;
    if (!el || !inner || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => { if (stick.current) el.scrollTop = el.scrollHeight; });
    observer.observe(inner);
    return () => observer.disconnect();
  }, [view]);
  useEffect(() => { if (status === "needs_agent" || status === "agent") input.current?.focus({ preventScroll: true }); }, [status]);

  const latestByCase = useMemo(() => {
    const map: Record<string, number> = {};
    conversation?.messages.forEach((m) => {
      const id = m.metadata.case_id as string | undefined;
      if (m.role === "assistant" && id) map[id] = Math.max(map[id] ?? 0, Number(m.metadata.attempt ?? 1));
    });
    return map;
  }, [conversation]);

  const submit = (e?: FormEvent, value?: string) => {
    e?.preventDefault();
    const message = (value ?? text).trim();
    if (message.length < 2 || send.isPending) return;
    stick.current = true;
    send.mutate(message);
    setText("");
  };

  if (view === "requests") {
    const cases = conversation?.cases ?? [];
    return (
      <div className="cw-body cw-requests">
        <button type="button" className="s-link-button" onClick={() => setView("chat")}>← Back to chat</button>
        <h3>Your support requests</h3>
        {cases.length === 0 && <p className="s-muted">Your requests from this chat will appear here.</p>}
        <ul>
          {cases.map((c) => (
            <li key={c.case_id}>
              <span>{c.complaint}</span>
              <small>Ref. {c.case_id} · {REQUEST_STATUS[c.status] ?? "In progress"}</small>
            </li>))}
        </ul>
      </div>
    );
  }

  const agentName = conversation?.assigned_agent ?? "Our support team";
  return (
    <>
      {status === "needs_agent" && (
        <div className="cw-banner" role="status">
          <span><b>Finding someone to help{conversation?.queue_position ? ` · you're number ${conversation.queue_position} in line` : ""}.</b> Their reply will show up here. You can keep chatting meanwhile.</span>
          <button type="button" className="s-link-button" disabled={human.isPending} onClick={() => human.mutate("cancel")}>Cancel</button>
        </div>
      )}
      {status === "agent" && <div className="cw-banner live" role="status"><span><b>{agentName}</b> is helping you now.</span></div>}
      <div className="cw-body" ref={body} aria-live="polite"
        onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120; }}>
        <div className="cw-thread" ref={thread}>
          {!conversation && <div className="cw-note">Loading your chat…</div>}
          {conversation?.messages.map((m) => <Bubble key={m.id} m={m} sessionId={sessionId} latestByCase={latestByCase} />)}
          {send.isPending && <div className="cw-row"><div className="cw-bubble bot cw-typing"><span /><span /><span /></div></div>}
          {count <= 1 && status === "bot" && (
            <div className="cw-starters">
              {STARTERS.map((s) => <button key={s} type="button" onClick={() => submit(undefined, s)}>{s}</button>)}
            </div>
          )}
        </div>
      </div>
      <form className="cw-input" onSubmit={submit}>
        <label htmlFor="cw-text" className="sr-only">Message</label>
        <input id="cw-text" ref={input} value={text} maxLength={2000} onChange={(e) => setText(e.target.value)}
          placeholder={status === "agent" ? `Message ${agentName}…` : "Type your message…"} />
        <VoiceButton disabled={send.isPending} onTranscript={(t) => setText((p) => (p ? `${p} ${t}` : t))} />
        <button type="submit" className="cw-send" aria-label="Send message" disabled={send.isPending || text.trim().length < 2}><Icon name="send" size={16} /></button>
      </form>
      <div className="cw-footer-actions">
        {(status === "bot" || status === "closed") && (
          <button type="button" className="s-link-button" disabled={human.isPending} onClick={() => human.mutate("request")}>Talk to a person</button>)}
        <button type="button" className="s-link-button" onClick={() => setView("requests")}>Your requests</button>
        <button type="button" className="s-link-button" onClick={onNewChat}>New chat</button>
      </div>
    </>
  );
}

/** Provides the floating chat widget for the whole customer site. */
export function ChatWidgetProvider({ children, initiallyOpen = false }: { children: ReactNode; initiallyOpen?: boolean }) {
  const { notify } = useToast();
  const [isOpen, setOpen] = useState(initiallyOpen);
  const [sessionId, setSessionId] = useState<string | null>(() => read(STORE_KEY));
  const [view, setView] = useState<"chat" | "requests">("chat");
  const [pending, setPending] = useState<OpenOptions | null>(null);
  const [seen, setSeen] = useState<number>(() => Number(read(SEEN_KEY) ?? 0));

  const chat = useQuery({
    queryKey: ["conversation", sessionId], queryFn: () => api.conversation(sessionId!), enabled: !!sessionId,
    refetchInterval: isOpen ? 3000 : 6000,
  });
  const conversation = chat.data;
  const resetChat = useCallback(() => { write(STORE_KEY, null); setSessionId(null); setView("chat"); }, []);
  useEffect(() => { if (chat.error instanceof ApiError && chat.error.status === 404) resetChat(); }, [chat.error, resetChat]);

  const start = useMutation({
    mutationFn: (name: string) => api.startConversation(name),
    onSuccess: (c) => { write(STORE_KEY, c.session_id); setSessionId(c.session_id); },
    onError: (e: Error) => notify(e.message, "error"),
  });

  // Unread replies (assistant, agent or notices) that arrived while the widget was closed.
  const lastId = conversation?.messages.at(-1)?.id ?? 0;
  useEffect(() => {
    if (isOpen && lastId > seen) { setSeen(lastId); write(SEEN_KEY, String(lastId)); }
  }, [isOpen, lastId, seen]);
  const unread = !isOpen && conversation ? conversation.messages.filter((m) => m.id > seen && m.role !== "user").length : 0;

  const open = useCallback((options: OpenOptions = {}) => {
    setOpen(true);
    setView(options.view ?? "chat");
    if (options.message || options.human) setPending(options);
  }, []);
  const value = useMemo(() => ({ open }), [open]);
  const status = conversation?.handoff_status ?? "bot";
  const agent = status === "agent" ? conversation?.assigned_agent : null;

  return (
    <ChatContext.Provider value={value}>
      {children}
      {isOpen ? (
        <section className="cw-panel" aria-label="Support chat">
          <header className="cw-head">
            {agent ? <span className="cw-avatar person"><Icon name="user" size={18} /></span> : <Logo size={34} />}
            <div className="cw-title">
              <b>{agent ?? "Support IQ"}</b>
              <span className={`cw-status ${status}`}>{sessionId ? STATUS_LINE[status] : "We usually reply instantly"}</span>
            </div>
            <button type="button" className="cw-icon" aria-label="Minimise chat" onClick={() => setOpen(false)}><Icon name="x" size={18} /></button>
          </header>
          {sessionId
            ? <ChatBody sessionId={sessionId} conversation={conversation} view={view} setView={setView} onNewChat={resetChat}
                pending={pending} clearPending={() => setPending(null)} />
            : <StartForm pendingQuestion={pending?.message} busy={start.isPending} onStart={(n) => start.mutate(n)} />}
        </section>
      ) : (
        <button type="button" className="cw-launcher" onClick={() => open()} aria-label={unread ? `Chat with us, ${unread} new messages` : "Chat with us"}>
          <Icon name="chat" size={20} /><span>Chat with us</span>
          {unread > 0 && <span className="cw-unread">{unread}</span>}
        </button>
      )}
    </ChatContext.Provider>
  );
}
