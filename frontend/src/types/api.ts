export type EvidenceStatus = "known" | "uncertain" | "unknown";
export type Severity = "low" | "medium" | "high" | "critical";
export type Sentiment = "positive" | "neutral" | "negative" | "frustrated" | "urgent";
export type InputMode = "free_text" | "guided" | "voice";
export type FeedbackOutcome = "solved" | "partially_solved" | "not_solved";
export type StageName =
  | "understanding" | "embedding" | "retrieving" | "reranking"
  | "checking_evidence" | "generating" | "citing" | "complete";
export type StageStatus = "pending" | "running" | "success" | "warning" | "error" | "skipped";

export interface Entity { type: string; value: string }

export interface Analysis {
  intent: string;
  intent_display: string;
  intent_confidence: number;
  classification_method: string;
  category: string;
  subcategory: string | null;
  support_category: string;
  domain_category: string;
  product: string;
  severity: Severity;
  severity_reasons: string[];
  sentiment: Sentiment;
  sentiment_score: number;
  entities: Entity[];
  memory_entities: Entity[];
  candidates: { intent: string; rule_score: number; similarity: number }[];
  used_memory: boolean;
}

export interface Source {
  source_id: string;
  source_type: string;
  chunk_id: string;
  title: string;
  excerpt: string;
  content: string;
  intent: string;
  category: string;
  product: string;
  quality: number;
  semantic_raw: number;
  semantic_score: number;
  keyword_score: number;
  metadata_score: number;
  hybrid_score: number;
  reranker_score: number | null;
  final_score: number;
  extra: Record<string, unknown>;
}

export interface Evidence {
  score: number;
  status: EvidenceStatus;
  components: Record<string, number>;
  top_similarity: number;
  intent_match: number;
  relevant_sources: number;
  reasons: string[];
  thresholds: { known: number; unknown: number };
}

export interface Retrieval {
  evidence_score: number;
  evidence: Evidence;
  sources: Source[];
  semantic_used: boolean;
  keyword_used: boolean;
  vector_backend: string;
  reranker_method: string;
  filter_relaxed: boolean;
  degraded_reasons: string[];
  candidates_considered: number;
  excluded_source_ids: string[];
  latency_ms: number;
}

export interface Step {
  text: string;
  citations: string[];
  kind: "resolution" | "information_gathering";
  already_attempted: boolean;
}

export interface Resolution {
  status: EvidenceStatus;
  is_candidate: boolean;
  label: string;
  summary: string;
  diagnosis: string;
  steps: Step[];
  warnings: string[];
  escalation: boolean;
  escalation_reason: string | null;
  insufficient_evidence: boolean;
  follow_up_question: string | null;
  generator: string;
  guard_report: { removed_steps?: { text: string; reason: string }[]; removed_citations?: string[]; removed_figures?: number };
}

export interface CitationRef { source_id: string; source_type: string; title: string; excerpt: string; score: number }

export interface PipelineStage {
  name: StageName;
  label: string;
  status: StageStatus;
  duration_ms: number;
  detail: string;
}

export interface ResolveResponse {
  request_id: string;
  case_id: string;
  session_id: string;
  mode: string;
  case_status: string;
  attempt: { attempt_number: number; max_attempts: number; can_retry: boolean };
  analysis: Analysis;
  retrieval: Retrieval;
  resolution: Resolution;
  citations: CitationRef[];
  unknown_issue: { headline: string; message: string; evidence_score: number; top_similarity: number; intent_match: number } | null;
  memory: { summary: string; used: boolean; state: MemoryState; turns: number };
  pipeline: PipelineStage[];
  latency_ms: number;
}

export interface MemoryState {
  intent?: string;
  intent_display?: string;
  issue?: string;
  product?: string;
  category?: string;
  entities?: Entity[];
  troubleshooting?: string[];
  customer_context?: string[];
  previous_resolutions?: { case_id: string; attempt: number; status: string; summary: string }[];
  feedback?: { case_id: string; attempt: number; outcome: string; comment: string }[];
  last_case_id?: string;
}

export interface FeedbackResponse {
  feedback_id: number;
  case_id: string;
  attempt_number: number;
  outcome: FeedbackOutcome;
  next_action: "closed" | "candidate_created" | "provide_more_info" | "retry" | "escalated";
  message: string;
  candidate_id: string | null;
  case_status: string;
  attempts_remaining: number;
}

export interface CaseSummary {
  case_id: string;
  session_id: string;
  complaint: string;
  intent: string;
  intent_display: string;
  category: string;
  product: string;
  severity: Severity;
  sentiment: Sentiment;
  evidence_score: number;
  evidence_status: EvidenceStatus;
  status: string;
  current_attempt: number;
  escalated: boolean;
  input_mode: string;
  latency_ms: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface Attempt {
  id: number;
  attempt_number: number;
  status: EvidenceStatus;
  is_candidate: boolean;
  insufficient_evidence: boolean;
  summary: string;
  diagnosis: string;
  steps: Step[];
  warnings: string[];
  escalation: boolean;
  escalation_reason: string | null;
  follow_up_question: string | null;
  citations: CitationRef[];
  sources: Source[];
  evidence: Evidence;
  evidence_score: number;
  query: string;
  additional_info: string | null;
  excluded_source_ids: string[];
  generator: string;
  pipeline: PipelineStage[];
  retrieval_latency_ms: number;
  llm_latency_ms: number;
  total_latency_ms: number;
  created_at: string | null;
}

export interface CaseDetail extends CaseSummary {
  request_id: string;
  effective_query: string;
  guided_category: string | null;
  analysis: Analysis;
  escalation_reason: string | null;
  used_memory: boolean;
  max_attempts: number;
  attempts: Attempt[];
  feedback: { id: number; attempt_number: number; outcome: FeedbackOutcome; comment: string | null; retrieved_source_ids: string[]; created_at: string | null }[];
  candidates: { id: string; status: string; approved_article_id: string | null }[];
}

export interface KnowledgeArticle {
  id: number;
  article_id: string;
  version: number;
  title: string;
  content: string;
  category: string;
  intent: string;
  product: string;
  status: "ACTIVE" | "DRAFT" | "ARCHIVED";
  source: string;
  source_type: string;
  created_by: string;
  change_note: string | null;
  is_latest: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface KnowledgeDetail extends KnowledgeArticle { versions: KnowledgeArticle[]; indexed_chunks: number }

export interface Paged<T> { items: T[]; total: number; page: number; page_size: number }

export interface Candidate {
  id: string;
  case_id: string | null;
  origin: "live_feedback" | "kb_match" | "agent_resolved" | "dataset" | "demo_seed";
  complaint: string;
  intent: string;
  category: string;
  product: string;
  proposed_title: string;
  proposed_resolution: string;
  sources: { source_id: string; source_type: string; title: string; score: number }[];
  evidence_score: number;
  attempt_number: number;
  customer_feedback: string;
  occurrences: number;
  emerging_signal: boolean;
  status: "pending_review" | "approved" | "rejected";
  reviewer: string | null;
  review_notes: string | null;
  approved_article_id: string | null;
  dataset_record_ids: string[];
  created_at: string | null;
  reviewed_at: string | null;
}

export interface ReviewResult { item_id: string; status: string; article: KnowledgeArticle | null; indexed: boolean; index_version: number | null; dataset_record_id?: string | null; updated_article?: KnowledgeArticle | null }

export interface EmergingIssue {
  id: string;
  pattern_name: string;
  description: string;
  status: "NEW" | "UNDER_REVIEW" | "APPROVED" | "REJECTED";
  occurrences: number;
  avg_evidence_score: number;
  keywords: string[];
  example_complaints: string[];
  suggested_intent_name: string;
  suggested_category: string;
  created_intent: string | null;
  created_article_id: string | null;
  review_notes: string | null;
  created_at: string | null;
  updated_at: string | null;
  members?: { member_type: string; member_id: string; complaint: string; similarity: number; evidence_score: number; weight: number }[] | null;
}

export interface Intent {
  name: string;
  display_name: string;
  description: string;
  domain_category: string;
  support_category: string;
  default_product: string | null;
  keywords: string[];
  example_complaints: string[];
  clarifying_question: string | null;
  status: string;
  origin: string;
  created_at: string | null;
  ticket_count: number;
  case_count: number;
  active_articles: number;
}

export interface Category { name: string; parent_name: string | null; icon: string; description: string }

export interface IntentsResponse { intents: Intent[]; categories: Category[]; domain_categories: string[] }

export interface IntentCreatePayload {
  name: string;
  display_name?: string;
  description: string;
  parent_category: string;
  domain_category?: string;
  example_complaints: string[];
  keywords?: string[];
  clarifying_question?: string;
  resolution_title?: string;
  resolution_steps?: string[];
  created_by?: string;
}

export interface EvaluationRun {
  id: number;
  split: string;
  sample_size: number;
  status: string;
  metrics: {
    classification: { accuracy: number; precision_macro: number; recall_macro: number; f1_macro: number };
    retrieval: Record<string, number>;
    rag: { groundedness: number | null; citation_correctness: number | null; citation_completeness: number | null; answer_relevance: number | null };
    evidence_status_distribution: Record<string, number>;
    unknown_detection: { out_of_taxonomy_samples: number; flagged_not_known: number; detection_rate: number | null };
    end_to_end: { cases: number; resolution_success_rate: number | null; escalation_rate: number | null; average_attempts: number; average_response_ms: number };
    leakage_check: { evaluated_tickets_found_in_index: number };
    intents_in_sample: string[];
  };
  config: Record<string, unknown>;
  notes: string | null;
  duration_ms: number;
  created_at: string | null;
}

export interface AnalyticsResponse {
  stats: {
    total_tickets: number;
    dataset_tickets: number;
    live_cases: number;
    resolved_cases: number;
    resolved_live_cases: number;
    unknown_issues: number;
    uncertain_cases: number;
    knowledge_articles: number;
    draft_articles: number;
    pending_candidates: number;
    approved_candidates: number;
    rejected_candidates: number;
    emerging_open: number;
    intents: number;
    resolution_success_rate: number | null;
    escalation_rate: number | null;
    average_attempts: number;
    average_response_ms: number;
    average_evidence_score: number;
  };
  dataset_split_counts: Record<string, number>;
  case_status_counts: Record<string, number>;
  evidence_status_counts: Record<string, number>;
  feedback_counts: Record<string, number>;
  knowledge_status_counts: Record<string, number>;
  candidate_status_counts: Record<string, number>;
  activity: { date: string; known: number; uncertain: number; unknown: number }[];
  intent_distribution: { intent: string; count: number }[];
  dataset_category_distribution: { category: string; count: number }[];
  recent_cases: CaseSummary[];
  emerging_issues: EmergingIssue[];
  latest_evaluation: EvaluationRun | null;
  index: { documents: number; by_source_type: Record<string, number>; index_version: number; vector_backend: string };
}

export interface Health {
  status: "ok" | "degraded";
  app: string;
  version: string;
  mode: string;
  demo_mode: boolean;
  llm_provider: string;
  gemini_configured: boolean;
  database: { available: boolean; backend: string; using_fallback: boolean; pgvector: boolean; error: string | null };
  embeddings: { backend: string; model: string; dimension: number; loaded: boolean; error: string | null };
  reranker: { enabled: boolean; model: string; loaded: boolean; error: string | null };
  index: { documents: number; index_version: number; vector_backend: string; by_source_type: Record<string, number> };
  counts: { tickets?: number; active_articles?: number };
}

export interface SettingsResponse {
  mode: string;
  demo_mode: boolean;
  app_env: string;
  llm: { provider: string; gemini_model: string; gemini_configured: boolean };
  embedding: { model: string; backend: string; dimension: number };
  reranker: { model: string; enabled: boolean; loaded: boolean };
  tunable: {
    known_threshold: number; unknown_threshold: number; semantic_weight: number; keyword_weight: number;
    metadata_weight: number; top_k: number; max_resolution_attempts: number; reranker_enabled: boolean;
    emerging_similarity_threshold: number; emerging_min_cluster_size: number;
  };
  evidence_weights: Record<string, number>;
  limits: Record<string, number>;
}

export type HandoffStatus = "bot" | "needs_agent" | "agent" | "closed";

export interface Conversation {
  session_id: string;
  title: string;
  customer_name: string;
  channel: string;
  handoff_status: HandoffStatus;
  handoff_reason: string | null;
  assigned_agent: string | null;
  agent_unread: number;
  queue_position?: number | null;
  memory: MemoryState;
  memory_summary: string;
  messages: ChatMessage[];
  cases: CaseSummary[];
  created_at: string | null;
  updated_at: string | null;
}

export interface ChatMessage { id: number; role: "user" | "assistant" | "agent" | "system"; message: string; metadata: Record<string, unknown>; created_at: string }

export interface ConversationReply { session_id: string; handled_by: "bot" | "agent"; assistant_message: string | null; resolution: ResolveResponse | null; conversation: Conversation }

export interface InboxItem {
  session_id: string;
  title: string;
  customer_name: string;
  channel: string;
  handoff_status: HandoffStatus;
  handoff_reason: string | null;
  assigned_agent: string | null;
  agent_unread: number;
  open_cases: number;
  memory_summary: string;
  last_message: string;
  last_role: string | null;
  updated_at: string | null;
}

export interface SystemLog { id: number; created_at: string; level: string; event: string; request_id: string | null; session_id: string | null; case_id: string | null; payload: Record<string, unknown> }

export type StreamEvent =
  | { type: "stage"; name: StageName; label: string; status: StageStatus; duration_ms?: number; detail?: string }
  | { type: "result"; data: ResolveResponse }
  | { type: "error"; error: { code: string; message: string; request_id: string | null } };

export interface CandidateListParams { status?: string; origin?: string; page?: number; page_size?: number }
