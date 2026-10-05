import { useCallback, useRef, useState } from "react";
import { ApiError, api } from "../services/api";
import type {
  FeedbackOutcome, FeedbackResponse, InputMode, ResolveResponse, StageName, StageStatus, StreamEvent,
} from "../types/api";

export const STAGES: { name: StageName; label: string }[] = [
  { name: "understanding", label: "Understanding" },
  { name: "embedding", label: "Embedding" },
  { name: "retrieving", label: "Retrieving" },
  { name: "reranking", label: "Reranking" },
  { name: "checking_evidence", label: "Checking evidence" },
  { name: "generating", label: "Generating" },
  { name: "citing", label: "Citing" },
  { name: "complete", label: "Complete" },
];

export type StageState = Record<StageName, { status: StageStatus; detail: string; duration_ms?: number }>;

const initialStages = (): StageState =>
  Object.fromEntries(STAGES.map((s) => [s.name, { status: "pending", detail: "" }])) as StageState;

export type Phase = "idle" | "running" | "done" | "error";

/** Drives the complete adaptive workflow: resolve -> feedback -> retry / candidate / escalation. */
export function useResolution(sessionId: string) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [stages, setStages] = useState<StageState>(initialStages);
  const [result, setResult] = useState<ResolveResponse | null>(null);
  const [attempts, setAttempts] = useState<ResolveResponse[]>([]);
  const [feedback, setFeedback] = useState<FeedbackResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busyFeedback, setBusyFeedback] = useState(false);
  const runId = useRef(0);

  const onEvent = useCallback((id: number) => (event: StreamEvent) => {
    if (id !== runId.current || event.type !== "stage") return;
    setStages((prev) => ({
      ...prev,
      [event.name]: { status: event.status, detail: event.detail ?? prev[event.name].detail, duration_ms: event.duration_ms },
    }));
  }, []);

  const run = useCallback(async (executor: (emit: (e: StreamEvent) => void) => Promise<ResolveResponse>, keepHistory: boolean) => {
    const id = ++runId.current;
    setPhase("running");
    setError(null);
    setFeedback(null);
    setStages(initialStages());
    try {
      const data = await executor(onEvent(id));
      if (id !== runId.current) return null;
      setStages((prev) => {
        const next = { ...prev };
        data.pipeline.forEach((p) => { next[p.name] = { status: p.status, detail: p.detail, duration_ms: p.duration_ms }; });
        return next;
      });
      setResult(data);
      setAttempts((prev) => (keepHistory ? [...prev, data] : [data]));
      setPhase("done");
      return data;
    } catch (err) {
      if (id !== runId.current) return null;
      const apiError = err instanceof ApiError ? err : new ApiError("Unexpected error while resolving.", "CLIENT_ERROR", 0);
      setError(apiError);
      setStages((prev) => {
        const next = { ...prev };
        const running = STAGES.find((s) => next[s.name].status === "running");
        if (running) next[running.name] = { status: "error", detail: apiError.message };
        return next;
      });
      setPhase("error");
      return null;
    }
  }, [onEvent]);

  const submit = useCallback((complaint: string, guidedCategory: string | null, inputMode: InputMode) =>
    run((emit) => api.resolveStream({ session_id: sessionId, complaint, guided_category: guidedCategory, input_mode: inputMode }, emit), false),
  [run, sessionId]);

  const retry = useCallback((additionalInfo?: string) => {
    if (!result) return Promise.resolve(null);
    return run((emit) => api.retryStream({ case_id: result.case_id, additional_info: additionalInfo || null }, emit), true);
  }, [result, run]);

  const sendFeedback = useCallback(async (outcome: FeedbackOutcome, comment?: string) => {
    if (!result) return null;
    setBusyFeedback(true);
    setError(null);
    try {
      const response = await api.feedback({ case_id: result.case_id, outcome, attempt_number: result.attempt.attempt_number, comment: comment || null });
      setFeedback(response);
      return response;
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError("Could not record feedback.", "CLIENT_ERROR", 0));
      return null;
    } finally {
      setBusyFeedback(false);
    }
  }, [result]);

  const reset = useCallback(() => {
    runId.current++;
    setPhase("idle");
    setStages(initialStages());
    setResult(null);
    setAttempts([]);
    setFeedback(null);
    setError(null);
  }, []);

  return { phase, stages, result, attempts, feedback, error, busyFeedback, submit, retry, sendFeedback, reset };
}
