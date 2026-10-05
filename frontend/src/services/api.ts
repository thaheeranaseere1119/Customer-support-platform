import type {
  AnalyticsResponse, CandidateListParams, CaseDetail, CaseSummary, Candidate, Conversation, ConversationReply,
  EmergingIssue, EvaluationRun, InboxItem, FeedbackOutcome, FeedbackResponse, Health, IntentCreatePayload, IntentsResponse,
  InputMode, KnowledgeArticle, KnowledgeDetail, Paged, ResolveResponse, ReviewResult, SettingsResponse, StreamEvent, SystemLog,
} from "../types/api";

const BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "") + "/api/v1";

export class ApiError extends Error {
  code: string;
  status: number;
  requestId: string | null;
  details?: unknown;

  constructor(message: string, code: string, status: number, requestId: string | null = null, details?: unknown) {
    super(message);
    this.code = code;
    this.status = status;
    this.requestId = requestId;
    this.details = details;
  }
}

const FRIENDLY: Record<string, string> = {
  NETWORK_ERROR: "We couldn't reach the server. Check that the backend is running and try again.",
  TIMEOUT: "The request took too long. Please try again.",
  DATABASE_UNAVAILABLE: "The database is temporarily unavailable. Please try again shortly.",
};

async function parseError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    const err = body?.error;
    if (err) {
      const fields = err.details?.fields as { field: string; message: string }[] | undefined;
      const message = fields?.length ? `${err.message} ${fields.map((f) => `${f.field}: ${f.message}`).join("; ")}` : err.message;
      return new ApiError(FRIENDLY[err.code] ?? message, err.code, response.status, err.request_id ?? null, err.details);
    }
  } catch {
    /* non-JSON error body: typically a proxy/gateway error while the backend is down */
  }
  if (response.status >= 500) return new ApiError(FRIENDLY.NETWORK_ERROR, "BACKEND_UNAVAILABLE", response.status);
  return new ApiError(`Request failed (${response.status}).`, "HTTP_ERROR", response.status);
}

async function request<T>(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), init.timeoutMs ?? 30000);
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      signal: init.signal ?? controller.signal,
      headers: { "Content-Type": "application/json", ...(init.headers || {}) },
    });
  } catch (error) {
    const aborted = (error as Error)?.name === "AbortError";
    throw new ApiError(FRIENDLY[aborted ? "TIMEOUT" : "NETWORK_ERROR"], aborted ? "TIMEOUT" : "NETWORK_ERROR", 0);
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as T;
}

const post = <T>(path: string, body: unknown, timeoutMs?: number) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body), timeoutMs });
const put = <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) });

function qs(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") search.set(k, String(v));
  });
  const s = search.toString();
  return s ? `?${s}` : "";
}

/** Streams NDJSON pipeline events; falls back to the plain endpoint if streaming is unavailable. */
async function streamOrFallback(streamPath: string, plainPath: string, body: unknown,
  onEvent: (event: StreamEvent) => void): Promise<ResolveResponse> {
  let response: Response | null = null;
  try {
    response = await fetch(`${BASE}${streamPath}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    response = null;
  }
  if (response && !response.ok) throw await parseError(response);
  if (!response || !response.body) {
    const result = await post<ResolveResponse>(plainPath, body, 120000);
    result.pipeline.forEach((stage) => onEvent({ type: "stage", ...stage }));
    return result;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ResolveResponse | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    let index: number;
    while ((index = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, index).trim();
      buffer = buffer.slice(index + 1);
      if (!line) continue;
      const event = JSON.parse(line) as StreamEvent;
      onEvent(event);
      if (event.type === "result") result = event.data;
      if (event.type === "error") throw new ApiError(FRIENDLY[event.error.code] ?? event.error.message, event.error.code, 500, event.error.request_id);
    }
    if (done) break;
  }
  if (!result) throw new ApiError("The pipeline ended without a result.", "INCOMPLETE_STREAM", 500);
  return result;
}

export const api = {
  health: () => request<Health>("/health", { timeoutMs: 10000 }),
  resolveStream: (body: { session_id: string; complaint: string; guided_category?: string | null; input_mode: InputMode },
    onEvent: (e: StreamEvent) => void) => streamOrFallback("/resolve/stream", "/resolve", body, onEvent),
  retryStream: (body: { case_id: string; additional_info?: string | null }, onEvent: (e: StreamEvent) => void) =>
    streamOrFallback("/resolve/retry/stream", "/resolve/retry", body, onEvent),
  feedback: (body: { case_id: string; outcome: FeedbackOutcome; attempt_number?: number; comment?: string | null }) =>
    post<FeedbackResponse>("/feedback", body),
  cases: (params: { status?: string; evidence_status?: string; limit?: number; offset?: number } = {}) =>
    request<{ items: CaseSummary[]; total: number }>(`/cases${qs(params)}`),
  caseDetail: (id: string) => request<CaseDetail>(`/cases/${encodeURIComponent(id)}`),
  knowledge: (params: { status?: string; category?: string; intent?: string; q?: string; page?: number; page_size?: number }) =>
    request<Paged<KnowledgeArticle>>(`/knowledge${qs(params)}`),
  knowledgeDetail: (id: string) => request<KnowledgeDetail>(`/knowledge/${encodeURIComponent(id)}`),
  createKnowledge: (body: { title: string; content: string; category: string; intent: string; product?: string; status: "ACTIVE" | "DRAFT" }) =>
    post<KnowledgeArticle>("/knowledge", body),
  updateKnowledge: (id: string, body: Partial<Pick<KnowledgeArticle, "title" | "content" | "category" | "intent" | "product" | "status">> & { change_note?: string }) =>
    put<KnowledgeArticle>(`/knowledge/${encodeURIComponent(id)}`, body),
  approve: (id: string, body: { reviewer: string; notes?: string; title?: string; content?: string; intent?: string; category?: string }) =>
    post<ReviewResult>(`/knowledge/${encodeURIComponent(id)}/approve`, body),
  reject: (id: string, body: { reviewer: string; notes?: string }) => post<ReviewResult>(`/knowledge/${encodeURIComponent(id)}/reject`, body),
  candidates: (params: CandidateListParams) =>
    request<Paged<Candidate> & { counts: Record<string, number>; origin_counts: Record<string, number> }>(`/candidates${qs({ ...params })}`),
  emergingIssues: (status?: string) => request<EmergingIssue[]>(`/emerging-issues${qs({ status })}`),
  emergingIssue: (id: string) => request<EmergingIssue>(`/emerging-issues/${encodeURIComponent(id)}`),
  detectEmerging: () => post<{ pool_size: number; clusters: number; created: number; updated: number }>("/emerging-issues/detect", {}),
  setEmergingStatus: (id: string, status: "NEW" | "UNDER_REVIEW" | "REJECTED", notes?: string) =>
    post<EmergingIssue>(`/emerging-issues/${encodeURIComponent(id)}/status`, { status, notes }),
  createIntentFromIssue: (id: string, body: IntentCreatePayload) =>
    post<{ intent: { name: string }; article: KnowledgeArticle | null }>(`/emerging-issues/${encodeURIComponent(id)}/create-intent`, body),
  intents: () => request<IntentsResponse>("/intents"),
  createIntent: (body: IntentCreatePayload) => post<{ intent: { name: string }; article: KnowledgeArticle | null }>("/intents", body),
  inbox: (params: { handoff_status?: string; channel?: string } = {}) =>
    request<{ items: InboxItem[]; counts: Record<string, number> }>(`/conversations${qs(params)}`),
  startConversation: (customerName: string) => post<Conversation>("/conversations", { customer_name: customerName }),
  handoff: (id: string, body: { action: "request" | "cancel" | "take" | "release" | "close"; agent?: string; reason?: string; resolved?: boolean }) =>
    post<Conversation>(`/conversations/${encodeURIComponent(id)}/handoff`, body),
  agentMessage: (id: string, agent: string, message: string) =>
    post<Conversation>(`/conversations/${encodeURIComponent(id)}/agent-message`, { agent, message }),
  markRead: (id: string) => post<Conversation>(`/conversations/${encodeURIComponent(id)}/read`, {}),
  conversation: (id: string) => request<Conversation>(`/conversations/${encodeURIComponent(id)}`),
  sendMessage: (id: string, message: string) =>
    post<ConversationReply>(`/conversations/${encodeURIComponent(id)}/message`, { message }, 120000),
  analytics: () => request<AnalyticsResponse>("/analytics"),
  evaluate: (body: { split: "held_out_test" | "calibration"; limit: number }) =>
    post<EvaluationRun>("/analytics/evaluate", body, 600000),
  evaluations: () => request<{ items: EvaluationRun[] }>("/analytics/evaluations"),
  settings: () => request<SettingsResponse>("/settings"),
  updateSettings: (body: Partial<SettingsResponse["tunable"]>) => put<SettingsResponse>("/settings", body),
  logs: (limit = 30) => request<{ items: SystemLog[] }>(`/logs${qs({ limit })}`),
};
