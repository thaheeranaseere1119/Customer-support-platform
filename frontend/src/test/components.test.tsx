import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SourceProvider } from "../components/Citation";
import { ErrorState } from "../components/ErrorState";
import { FeedbackCard } from "../components/FeedbackCard";
import { ResolutionCard } from "../components/ResolutionCard";
import { UnknownIssueCard } from "../components/UnknownIssueCard";
import { VoiceButton } from "../components/VoiceButton";
import type { ResolveResponse } from "../types/api";
import known from "./fixtures/resolve-known.json";
import unknown from "./fixtures/resolve-unknown.json";

const KNOWN = known as unknown as ResolveResponse;
const UNKNOWN = unknown as unknown as ResolveResponse;

describe("ResolutionCard + citations", () => {
  it("renders grounded steps with clickable citations that open Source Details", () => {
    render(
      <SourceProvider sources={KNOWN.retrieval.sources} citations={KNOWN.citations}>
        <ResolutionCard resolution={KNOWN.resolution} attempt={1} />
      </SourceProvider>,
    );
    expect(screen.getByText("Suggested answer")).toBeInTheDocument();
    expect(screen.getByText("Verified answer")).toBeInTheDocument();
    expect(screen.getByText(/Customer already tried/)).toBeInTheDocument();
    expect(screen.getByText("Escalation recommended")).toBeInTheDocument();
    const citation = screen.getAllByRole("button", { name: "Open source KB-031" })[0];
    fireEvent.click(citation);
    const dialog = screen.getByRole("dialog", { name: "Source Details" });
    expect(within(dialog).getByText("Source ID")).toBeInTheDocument();
    expect(within(dialog).getAllByText(/KB-031/).length).toBeGreaterThan(0);
    expect(within(dialog).getByText(/Reranker/)).toBeInTheDocument();
  });

  it("shows unknown-issue evidence metrics", () => {
    render(<UnknownIssueCard unknown={UNKNOWN.unknown_issue!} />);
    expect(screen.getByText("No help article matches this problem yet")).toBeInTheDocument();
    expect(screen.getByText("Confidence")).toBeInTheDocument();
    expect(screen.getByText("Closest match")).toBeInTheDocument();
    expect(screen.getByText("Issue type match")).toBeInTheDocument();
  });

  it("labels information-gathering steps when evidence is insufficient", () => {
    render(<SourceProvider sources={[]} citations={[]}><ResolutionCard resolution={UNKNOWN.resolution} attempt={1} /></SourceProvider>);
    expect(screen.getAllByText("Information to collect").length).toBeGreaterThan(0);
    expect(screen.getByText("No matching help article")).toBeInTheDocument();
  });
});

describe("FeedbackCard", () => {
  it("sends each outcome", () => {
    const onFeedback = vi.fn();
    render(<FeedbackCard busy={false} onFeedback={onFeedback} />);
    expect(screen.getByText("Did this solve the problem?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Yes, solved/ }));
    fireEvent.click(screen.getByRole("button", { name: /Partly/ }));
    fireEvent.click(screen.getByRole("button", { name: /No, still not solved/ }));
    expect(onFeedback.mock.calls.map((c) => c[0])).toEqual(["solved", "partially_solved", "not_solved"]);
  });
});

describe("VoiceButton", () => {
  it("explains when the Web Speech API is unsupported instead of crashing", () => {
    render(<VoiceButton onTranscript={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Voice input is not supported in this browser." }));
    expect(screen.getByRole("alert")).toHaveTextContent("Voice input is not supported in this browser.");
  });

  it("feeds the transcript into the complaint when supported", () => {
    const instances: { onresult: ((e: unknown) => void) | null; onend: (() => void) | null }[] = [];
    class FakeRecognition {
      lang = ""; continuous = false; interimResults = false;
      onresult: ((e: unknown) => void) | null = null; onerror = null; onend: (() => void) | null = null;
      constructor() { instances.push(this); }
      start() {}
      stop() { this.onend?.(); }
    }
    (window as unknown as { webkitSpeechRecognition: unknown }).webkitSpeechRecognition = FakeRecognition;
    const onTranscript = vi.fn();
    render(<VoiceButton onTranscript={onTranscript} />);
    fireEvent.click(screen.getByRole("button", { name: "Speak the complaint" }));
    instances[0].onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: "my sim is not detected" } }] });
    expect(onTranscript).toHaveBeenCalledWith("my sim is not detected");
    delete (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;
  });
});

describe("ErrorState", () => {
  it("shows a friendly message and the request id, never a stack trace", () => {
    const retry = vi.fn();
    render(<ErrorState message="We couldn't reach the server." requestId="req_123" onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn't reach the server.");
    expect(screen.getByText(/req_123/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(retry).toHaveBeenCalled();
  });
});
