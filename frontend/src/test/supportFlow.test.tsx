import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SupportPage } from "../pages/SupportPage";
import intents from "./fixtures/intents.json";
import known from "./fixtures/resolve-known.json";
import unknown from "./fixtures/resolve-unknown.json";
import { jsonResponse, renderWithProviders } from "./render";

afterEach(() => vi.restoreAllMocks());

function mockBackend(resolveBody: unknown, extra: Record<string, unknown> = {}) {
  const calls: { url: string; body?: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url.endsWith("/intents")) return jsonResponse(intents);
    if (url.endsWith("/stream")) return jsonResponse({}); // no body: client falls back to the plain endpoint
    if (url.endsWith("/resolve")) return jsonResponse(resolveBody);
    for (const [suffix, body] of Object.entries(extra)) if (url.endsWith(suffix)) return jsonResponse(body);
    return jsonResponse({}, 404);
  });
  return calls;
}

describe("Support resolution flow (frontend E2E with mocked API)", () => {
  it("submits a complaint and displays analysis, evidence, resolution and citations", async () => {
    const calls = mockBackend(known);
    renderWithProviders(<SupportPage sessionId="session-test" onNewSession={() => undefined} />, "/support");
    fireEvent.change(screen.getByPlaceholderText("Describe the issue in your own words..."),
      { target: { value: "My broadband drops every evening around 8 PM and I already restarted the router twice." } });
    fireEvent.click(screen.getByRole("button", { name: /Submit Complaint/ }));

    expect(await screen.findByText("Issue summary")).toBeInTheDocument();
    expect(screen.getAllByText("Broadband Disconnect").length).toBeGreaterThan(0);
    expect(screen.getByText((known as { analysis: { severity: string } }).analysis.severity.toUpperCase())).toBeInTheDocument();
    expect(screen.getByText("Sources the assistant found")).toBeInTheDocument();
    expect(screen.getByText("Suggested answer")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Open source KB-031" }).length).toBeGreaterThan(0);
    expect(screen.getByText("Did this solve the problem?")).toBeInTheDocument();
    const resolveCall = calls.find((c) => c.url.endsWith("/resolve"));
    expect(resolveCall?.body).toMatchObject({ session_id: "session-test", input_mode: "free_text" });
  });

  it("guided category and free text converge on the same resolve call", async () => {
    const calls = mockBackend(known);
    renderWithProviders(<SupportPage sessionId="session-test" onNewSession={() => undefined} />, "/support");
    fireEvent.click(await screen.findByRole("button", { name: "Billing" }));
    fireEvent.click(screen.getAllByRole("button", { name: /“/ })[0]);
    fireEvent.click(screen.getByRole("button", { name: /Submit Complaint/ }));
    await screen.findByText("Issue summary");
    const body = calls.find((c) => c.url.endsWith("/resolve/stream"))?.body as Record<string, unknown>;
    expect(body.guided_category).toBe("Billing");
    expect(body.input_mode).toBe("guided");
  });

  it("shows the unknown-issue workflow and adaptive retry after NO", async () => {
    const retried = { ...unknown, attempt: { attempt_number: 2, max_attempts: 3, can_retry: true } };
    const calls = mockBackend(unknown, {
      "/feedback": { feedback_id: 1, case_id: (unknown as { case_id: string }).case_id, attempt_number: 1, outcome: "not_solved",
        next_action: "retry", message: "Not solved.", candidate_id: null, case_status: "retry_pending", attempts_remaining: 2 },
      "/resolve/retry": retried,
    });
    renderWithProviders(<SupportPage sessionId="session-test" onNewSession={() => undefined} />, "/support");
    fireEvent.change(screen.getByPlaceholderText("Describe the issue in your own words..."), { target: { value: "My kids smartwatch location sharing stopped" } });
    fireEvent.click(screen.getByRole("button", { name: /Submit Complaint/ }));
    expect(await screen.findByText("No help article matches this problem yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /No, still not solved/ }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/resolve/retry/stream"))).toBe(true));
    expect(await screen.findByText(/Attempt 2 of 3/)).toBeInTheDocument();
  });

  it("shows a friendly error when the backend fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/intents")) return jsonResponse(intents);
      return jsonResponse({ error: { code: "RETRIEVAL_FAILED", message: "Unable to retrieve evidence.", request_id: "req_9" } }, 502);
    });
    renderWithProviders(<SupportPage sessionId="session-test" onNewSession={() => undefined} />, "/support");
    fireEvent.change(screen.getByPlaceholderText("Describe the issue in your own words..."), { target: { value: "My SIM is not detected" } });
    fireEvent.click(screen.getByRole("button", { name: /Submit Complaint/ }));
    expect(await screen.findByText("Unable to retrieve evidence.")).toBeInTheDocument();
    expect(screen.getByText(/req_9/)).toBeInTheDocument();
  });
});
