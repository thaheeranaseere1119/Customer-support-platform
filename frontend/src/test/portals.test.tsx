import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";
import { InboxPage } from "../pages/InboxPage";
import { ArticlePage } from "../site/ArticlePage";
import { customerHeadline } from "../site/ChatWidget";
import { HomePage } from "../site/HomePage";
import { NotFoundPage } from "../site/NotFoundPage";
import { SiteLayout } from "../site/SiteLayout";
import intents from "./fixtures/intents.json";
import { jsonResponse, renderWithProviders } from "./render";

afterEach(() => { vi.restoreAllMocks(); window.localStorage.clear(); });

const article = (id: string, title: string, category: string, intent: string, source = "synthetic_demo_kb") => ({
  id: Number(id.slice(3)), article_id: id, version: 1, title, category, intent, product: "", status: "ACTIVE", source,
  source_type: "synthetic_knowledge_article", created_by: "seed", change_note: null, is_latest: true,
  created_at: "2026-01-01T00:00:00", updated_at: "2026-09-12T10:00:00",
  content: "Symptoms: The phone reports no SIM.\nResolution steps:\n1. Power off the device.\n2. Reseat the SIM if appropriate.\n"
    + "Escalate when: The SIM remains undetected.\nCaution: Do not ask the customer to cut the SIM.\nSource note: SYNTHETIC / DEMO DATA",
});
const ARTICLES = [
  article("KB-028", "SIM not detected by the device", "SIM", "sim_not_detected"),
  article("KB-032", "Duplicate charge review", "Billing", "billing_dispute"),
];

const baseChat = {
  session_id: "chat-abc", title: "t", customer_name: "Asha", channel: "customer_app", handoff_status: "bot",
  handoff_reason: null, assigned_agent: null, agent_unread: 0, queue_position: null, memory: {}, memory_summary: "", cases: [],
  created_at: null, updated_at: null,
  messages: [{ id: 1, role: "assistant", message: "Hi Asha! What can I help you with today?", metadata: { type: "greeting" }, created_at: "2026-10-02T10:00:00" }],
};

function siteRoutes() {
  return (
    <Routes>
      <Route element={<SiteLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/help/article/:articleId" element={<ArticlePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

function mockApi(chat: { current: Record<string, unknown> } = { current: baseChat }) {
  const calls: { method: string; url: string; body?: Record<string, unknown> }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method: init?.method ?? "GET", url, body });
    if (url.endsWith("/intents")) return jsonResponse(intents);
    if (url.includes("/knowledge?")) return jsonResponse({ items: ARTICLES, total: ARTICLES.length, page: 1, page_size: 100 });
    if (url.includes("/knowledge/KB-028")) return jsonResponse({ ...ARTICLES[0], versions: [], indexed_chunks: 1 });
    if (url.endsWith("/conversations") && init?.method === "POST") return jsonResponse(chat.current, 201);
    if (url.endsWith("/handoff")) {
      chat.current = body?.action === "cancel"
        ? { ...chat.current, handoff_status: "bot", queue_position: null }
        : { ...chat.current, handoff_status: "needs_agent", queue_position: 2 };
      return jsonResponse(chat.current);
    }
    if (url.includes("/conversations/")) return jsonResponse(chat.current);
    return jsonResponse({}, 404);
  });
  return calls;
}

describe("Customer help center", () => {
  it("searches real help articles and offers the assistant when nothing matches", async () => {
    mockApi();
    renderWithProviders(siteRoutes(), "/");
    expect(screen.getByRole("heading", { name: "How can we help?" })).toBeInTheDocument();
    const search = screen.getByRole("searchbox", { name: "Search help articles" });
    fireEvent.change(search, { target: { value: "sim detected" } });
    const results = await screen.findByRole("region", { name: "Search results" });
    expect(await within(results).findByRole("link", { name: /SIM not detected by the device/ })).toHaveAttribute("href", "/help/article/KB-028");
    fireEvent.change(search, { target: { value: "satellite texting" } });
    expect(await screen.findByText(/Try different words/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ask our assistant about “satellite texting”/ })).toBeInTheDocument();
  });

  it("shows topics, a footer with staff login, and no internal IDs or AI jargon", async () => {
    mockApi();
    renderWithProviders(siteRoutes(), "/");
    expect(await screen.findByRole("link", { name: /Billing/ })).toHaveAttribute("href", "/help/topic/Billing");
    expect(screen.getByRole("link", { name: "Staff login" })).toHaveAttribute("href", "/admin");
    expect(document.body.textContent).not.toMatch(/KB-\d|RAG|evidence|SYNTHETIC/);
  });

  it("article pages show customer steps but hide agent-only notes", async () => {
    mockApi();
    renderWithProviders(siteRoutes(), "/help/article/KB-028");
    expect(await screen.findByRole("heading", { level: 1, name: "SIM not detected by the device" })).toBeInTheDocument();
    expect(screen.getByText("Power off the device.")).toBeInTheDocument();
    expect(screen.getByText(/Last updated/)).toBeInTheDocument();
    expect(screen.queryByText(/Do not ask the customer/)).not.toBeInTheDocument();
    expect(screen.queryByText(/remains undetected/)).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Help center/SIM/SIM not detected by the device");
  });

  it("unknown pages show a friendly 404", () => {
    mockApi();
    renderWithProviders(siteRoutes(), "/no-such-page");
    expect(screen.getByRole("heading", { name: "This page has moved" })).toBeInTheDocument();
  });
});

describe("Chat widget", () => {
  it("starts a chat, asks for a person, shows the queue and can cancel", async () => {
    const chat = { current: baseChat as Record<string, unknown> };
    const calls = mockApi(chat);
    renderWithProviders(siteRoutes(), "/");
    fireEvent.click(screen.getAllByRole("button", { name: "Chat with us" })[0]);
    fireEvent.change(screen.getByLabelText("Your first name"), { target: { value: "Asha" } });
    fireEvent.click(screen.getByRole("button", { name: "Start chat" }));
    expect(await screen.findByText("Hi Asha! What can I help you with today?")).toBeInTheDocument();
    const panel = screen.getByRole("region", { name: "Support chat" });
    fireEvent.click(within(panel).getByRole("button", { name: "Talk to a person" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/handoff") && c.body?.action === "request")).toBe(true));
    expect(await screen.findByText(/you're number 2 in line/)).toBeInTheDocument();
    fireEvent.click(within(panel).getByRole("button", { name: "Cancel" }));
    expect(await within(panel).findByRole("button", { name: "Talk to a person" })).toBeEnabled();
  });

  it("shows replies from a person on the support team", async () => {
    window.localStorage.setItem("telecom-customer-chat", "chat-abc");
    const withAgent = { ...baseChat, handoff_status: "agent", assigned_agent: "Priya", messages: [...baseChat.messages,
      { id: 2, role: "agent", message: "Hi, Priya here.", metadata: { agent: "Priya" }, created_at: "2026-10-02T10:01:00" }] };
    mockApi({ current: withAgent });
    renderWithProviders(siteRoutes(), "/?chat=open");
    expect(await screen.findByText("Hi, Priya here.")).toBeInTheDocument();
    expect(screen.getByText(/is helping you now/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Message Priya…")).toBeInTheDocument();
  });

  it("uses plain language for customers", () => {
    expect(customerHeadline("Verified evidence matches 'X'.", "known", 1)).toBe("Here's what usually fixes this:");
    expect(customerHeadline("BEST-SUITABLE GUIDANCE - ...", "unknown", 1)).toBe("Here are the steps that help most with issues like this:");
    expect(customerHeadline("CANDIDATE RESOLUTION - ...", "uncertain", 2)).toBe("Here's another approach to try:");
    expect(customerHeadline("The evidence is insufficient: ...", "unknown", 2)).toMatch(/^Let's narrow this down together/);
    for (const [msg, status, n] of [["BEST-SUITABLE GUIDANCE", "unknown", 1], ["x", "uncertain", 1], ["The evidence is insufficient", "unknown", 3]] as const) {
      expect(customerHeadline(msg, status, n)).not.toMatch(/\b(no|not|couldn't|can't|don't|unable|sorry)\b/i);
    }
  });
});

describe("Admin inbox", () => {
  it("lists chats needing an agent and can take over", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.includes("/conversations?") || url.endsWith("/conversations")) {
        return jsonResponse({ items: [{ session_id: "chat-abc", title: "t", customer_name: "Asha", channel: "customer_app",
          handoff_status: "needs_agent", handoff_reason: "Customer asked for a human agent", assigned_agent: null, agent_unread: 2,
          open_cases: 1, memory_summary: "", last_message: "Thanks, we're finding someone…", last_role: "system", updated_at: null }],
          counts: { needs_agent: 1 } });
      }
      if (url.endsWith("/handoff")) return jsonResponse({ ...baseChat, handoff_status: "agent", assigned_agent: "Support agent" });
      return jsonResponse({ ...baseChat, handoff_status: "needs_agent", handoff_reason: "Customer asked for a human agent" });
    });
    renderWithProviders(<InboxPage />, "/admin/inbox");
    expect(await screen.findByRole("tab", { name: "Waiting (1)" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Assign to me/ }));
    await waitFor(() => expect(calls.some((c) => c.startsWith("POST") && c.endsWith("/handoff"))).toBe(true));
  });
});

describe("Chat replies", () => {
  it("opens with the line written for this customer's question", async () => {
    const { ChatWidgetProvider } = await import("../site/ChatWidget");
    window.localStorage.setItem("telecom-customer-chat", "chat-abc");
    const chat = { ...baseChat, messages: [...baseChat.messages,
      { id: 2, role: "user", message: "my broadband drops every evening", metadata: {}, created_at: "2026-10-02T10:01:00" },
      { id: 3, role: "assistant", message: "Verified evidence…", created_at: "2026-10-02T10:01:02",
        metadata: { case_id: "CASE-1", attempt: 1, status: "known",
          customer_intro: "Sorry your broadband keeps dropping every evening. Let's get your connection stable again:" } }] };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      jsonResponse(String(input).includes("/cases/") ? { case_id: "CASE-1", status: "awaiting_feedback", current_attempt: 1, attempts: [] } : chat));
    renderWithProviders(<ChatWidgetProvider initiallyOpen><div /></ChatWidgetProvider>);
    expect(await screen.findByText("Sorry your broadband keeps dropping every evening. Let's get your connection stable again:")).toBeInTheDocument();
    expect(screen.queryByText("Here's what usually fixes this:")).not.toBeInTheDocument();
  });
});
