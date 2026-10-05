import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CandidatesPage } from "../pages/CandidatesPage";
import intents from "./fixtures/intents.json";
import { jsonResponse, renderWithProviders } from "./render";

afterEach(() => vi.restoreAllMocks());

describe("Knowledge evolution stepper", () => {
  it("every workflow step is clickable and filters the queue to that stage", async () => {
    const urls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      urls.push(url);
      if (url.endsWith("/intents")) return jsonResponse(intents);
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 15,
        counts: { pending_review: 12, approved: 10 }, origin_counts: { live_feedback: 2, dataset: 10, demo_seed: 12 } });
    });
    renderWithProviders(<CandidatesPage />, "/candidates");
    const step1 = await screen.findByRole("button", { name: /Confirmed by customers/ });
    const step2 = screen.getByRole("button", { name: /Waiting for review/ });
    const step3 = screen.getByRole("button", { name: /Published as help articles/ });
    expect(step2).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(step1);
    await waitFor(() => expect(urls.some((u) => u.includes("origin=live_feedback") && !u.includes("status="))).toBe(true));
    expect(step1).toHaveAttribute("aria-pressed", "true");
    expect(step2).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(step3);
    await waitFor(() => expect(urls.some((u) => u.includes("status=approved"))).toBe(true));
    expect(step3).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(step2);
    await waitFor(() => expect(step2).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("tab", { name: /All \(22\)/ })).toBeInTheDocument();
  });
});
