import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { AdaptiveResolutionCard } from "../components/AdaptiveResolutionCard";
import { AnalysisCard } from "../components/AnalysisCard";
import { SourceProvider } from "../components/Citation";
import { ComplaintInput } from "../components/ComplaintInput";
import { ErrorState } from "../components/ErrorState";
import { FeedbackCard } from "../components/FeedbackCard";
import { Icon } from "../components/Icon";
import { MemoryPanel } from "../components/MemoryPanel";
import { ProcessingPipeline } from "../components/ProcessingPipeline";
import { ResolutionCard } from "../components/ResolutionCard";
import { RetrievalResults } from "../components/RetrievalResults";
import { UnknownIssueCard } from "../components/UnknownIssueCard";
import { useResolution } from "../hooks/useResolution";
import { useToast } from "../hooks/useToast";
import { api } from "../services/api";
import type { FeedbackOutcome } from "../types/api";

export function SupportPage({ sessionId, onNewSession }: { sessionId: string; onNewSession: () => void }) {
  const flow = useResolution(sessionId);
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const intents = useQuery({ queryKey: ["intents"], queryFn: api.intents });
  const top = useRef<HTMLDivElement>(null);

  const categoryExamples = useMemo(() => {
    const map: Record<string, string[]> = {};
    const cats = intents.data?.categories ?? [];
    intents.data?.intents.forEach((i) => {
      const parent = cats.find((c) => c.name === i.support_category)?.parent_name;
      [i.support_category, parent].filter(Boolean).forEach((c) => { map[c as string] = [...(map[c as string] ?? []), ...i.example_complaints.slice(0, 1)]; });
    });
    return map;
  }, [intents.data]);

  const { result, feedback, retry } = flow;
  // Adaptive workflow: NO -> automatically retrieve alternative evidence for the next attempt.
  const autoRetried = useRef<number | null>(null);
  useEffect(() => {
    if (feedback?.next_action === "retry" && autoRetried.current !== feedback.feedback_id) {
      autoRetried.current = feedback.feedback_id;
      retry();
    }
  }, [feedback, retry]);

  const refreshLists = () => queryClient.invalidateQueries();

  const onFeedback = async (outcome: FeedbackOutcome, comment?: string) => {
    const response = await flow.sendFeedback(outcome, comment);
    if (!response) return;
    refreshLists();
    const messages = {
      closed: ["Marked as solved.", "success"], candidate_created: ["Saved as candidate knowledge, pending human verification.", "success"],
      retry: ["Not solved. Running an adaptive retry with alternative evidence…", "info"],
      provide_more_info: ["Partially solved. Add more information, then retry.", "info"],
      escalated: ["Maximum attempts reached. Case escalated to a human agent.", "error"],
    } as const;
    const [message, kind] = messages[response.next_action];
    notify(message, kind);
  };

  const submit: Parameters<typeof ComplaintInput>[0]["onSubmit"] = async (complaint, category, mode) => {
    const data = await flow.submit(complaint, category, mode);
    if (data) { refreshLists(); top.current?.scrollIntoView?.({ behavior: "smooth" }); }
  };

  const citedIds = useMemo(() => new Set(result?.citations.map((c) => c.source_id) ?? []), [result]);
  const awaitingFeedback = result && flow.phase === "done" && !feedback && result.case_status === "awaiting_feedback";
  const running = flow.phase === "running";

  return (
    <div className="support-layout">
      <div className="support-left">
        <ComplaintInput categories={intents.data?.categories ?? []} categoryExamples={categoryExamples} busy={running} onSubmit={submit} />
        {intents.error && <ErrorState title="Categories unavailable" message={(intents.error as Error).message} onRetry={() => intents.refetch()} />}
        <MemoryPanel memory={result?.memory.state ?? {}} summary={result?.memory.summary} />
        <div className="row">
          <span className="tiny muted mono">Session {sessionId}</span><span className="spacer" />
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { flow.reset(); onNewSession(); notify("Started a new session; memory cleared for new complaints.", "info"); }}>
            <Icon name="refresh" size={14} />New session</button>
        </div>
      </div>

      <div className="stack" ref={top} style={{ gap: 20 }}>
        {flow.phase === "running" ? (
          <section className="card" aria-label="Assistant progress">
            <div className="card-header"><h2 className="card-title">Working on it…</h2></div>
            <ProcessingPipeline stages={flow.stages} />
          </section>
        ) : result && (
          <details className="details" aria-label="Assistant progress">
            <summary>How this answer was found · {Math.round(result.latency_ms)} ms</summary>
            <div className="details-body">
              <ProcessingPipeline stages={flow.stages} />
              <p className="tiny muted" style={{ marginTop: 10 }}>Request <span className="mono">{result.request_id}</span></p>
            </div>
          </details>
        )}

        {flow.error && <ErrorState message={flow.error.message} requestId={flow.error.requestId} />}

        {!result && flow.phase !== "running" && !flow.error && (
          <section className="card empty-state">
            <h2 className="card-title">Try a customer message</h2>
            <p className="muted" style={{ maxWidth: 460, margin: "8px auto 0" }}>Type or speak a complaint the way a customer would, and see which help articles and past cases the assistant uses to answer it.</p>
          </section>
        )}

        {result && (
          <SourceProvider sources={result.retrieval.sources} citations={result.citations}>
            {result.unknown_issue && <UnknownIssueCard unknown={result.unknown_issue} />}
            <AnalysisCard analysis={result.analysis} />
            <RetrievalResults retrieval={result.retrieval} citedIds={citedIds} />
            <ResolutionCard resolution={result.resolution} attempt={result.attempt.attempt_number} />
            {awaitingFeedback && <FeedbackCard busy={flow.busyFeedback} onFeedback={onFeedback} />}
            <AdaptiveResolutionCard attempts={flow.attempts} maxAttempts={result.attempt.max_attempts} feedback={feedback}
              busy={running} onRetry={(info) => flow.retry(info).then((d) => { if (d) refreshLists(); })} />
          </SourceProvider>
        )}
      </div>
    </div>
  );
}
