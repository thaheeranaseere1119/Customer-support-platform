import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantResolution } from "../components/AssistantResolution";
import known from "./fixtures/resolve-known.json";
import { jsonResponse, renderWithProviders } from "./render";

afterEach(() => vi.restoreAllMocks());

const r = known as unknown as {
  case_id: string; resolution: { steps: unknown[]; warnings: string[]; escalation: boolean; escalation_reason: string | null };
  citations: unknown[]; retrieval: { sources: unknown[]; evidence_score: number };
};
const caseDetail = {
  case_id: r.case_id, status: "awaiting_feedback", current_attempt: 1, max_attempts: 3, escalation_reason: null,
  attempts: [{ attempt_number: 1, status: "known", is_candidate: false, steps: r.resolution.steps, citations: r.citations,
    sources: r.retrieval.sources, warnings: r.resolution.warnings, escalation: r.resolution.escalation,
    escalation_reason: r.resolution.escalation_reason, evidence_score: r.retrieval.evidence_score }],
};

function mockCase() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => jsonResponse(caseDetail));
}

describe("AssistantResolution audiences", () => {
  it("customers never see internal scores, even when the answer is not interactive", async () => {
    mockCase();
    renderWithProviders(<AssistantResolution caseId={r.case_id} attempt={1} sessionId="s" audience="customer" interactive={false} />);
    expect(await screen.findByLabelText("Suggested solution")).toBeInTheDocument();
    expect(screen.queryByText(/Evidence 0\./)).not.toBeInTheDocument();
    expect(screen.queryByText("VERIFIED RESOLUTION")).not.toBeInTheDocument();
    expect(screen.queryByText(/KB-\d/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Evening broadband drops/ })).toHaveAttribute("href", "/help/article/KB-031");
    expect(screen.queryByText("Did this solve it?")).not.toBeInTheDocument();
  });

  it("customers get the feedback question on the latest answer", async () => {
    mockCase();
    renderWithProviders(<AssistantResolution caseId={r.case_id} attempt={1} sessionId="s" audience="customer" interactive />);
    expect(await screen.findByText("Did this solve it?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yes, all sorted" })).toBeInTheDocument();
  });

  it("new questions also link the closest help articles, in positive wording", async () => {
    const unknownCase = { ...caseDetail, attempts: [{ ...caseDetail.attempts[0], status: "unknown", is_candidate: true, citations: [] }] };
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => jsonResponse(unknownCase));
    renderWithProviders(<AssistantResolution caseId={r.case_id} attempt={1} sessionId="s" audience="customer" interactive />);
    expect(await screen.findByText("You might also find these helpful:")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Evening broadband drops/ })).toHaveAttribute("href", "/help/article/KB-031");
    expect(screen.getByRole("button", { name: "I still need help" })).toBeInTheDocument();
    expect(screen.getByLabelText("Suggested solution").textContent).not.toMatch(/\b(couldn't|can't|haven't|not confirmed|unable|sorry)\b/i);
  });

  it("customers read the plain customer wording; agent-only steps are left out", async () => {
    const steps = [
      { text: "Restart the router/ONT.", citations: ["KB-009"], kind: "resolution", already_attempted: false,
        customer_text: "Restart your router (and your fibre box, if you have one)." },
      { text: "Treat as critical.", citations: ["KB-009"], kind: "resolution", already_attempted: false, customer_text: "" },
    ];
    const worded = { ...caseDetail, attempts: [{ ...caseDetail.attempts[0], steps }] };
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => jsonResponse(worded));
    renderWithProviders(<AssistantResolution caseId={r.case_id} attempt={1} sessionId="s" audience="customer" interactive />);
    expect(await screen.findByText("Restart your router (and your fibre box, if you have one).")).toBeInTheDocument();
    expect(screen.queryByText("Restart the router/ONT.")).not.toBeInTheDocument();
    expect(screen.queryByText("Treat as critical.")).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem").filter((li) => li.closest(".cr-steps"))).toHaveLength(1);
  });

  it("admins see the evidence details", async () => {
    mockCase();
    renderWithProviders(<AssistantResolution caseId={r.case_id} attempt={1} sessionId="s" audience="admin" interactive={false} />);
    expect(await screen.findByText("VERIFIED RESOLUTION")).toBeInTheDocument();
    expect(screen.getByText(/Evidence 0\.\d+ · attempt 1\/3/)).toBeInTheDocument();
  });
});
