import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { getStaffToken, setStaffToken } from "../hooks/useStaffSession";
import { api } from "../services/api";
import { jsonResponse, renderWithProviders } from "./render";

afterEach(() => { vi.restoreAllMocks(); window.localStorage.clear(); });

const authHeader = (call: unknown[]) => ((call[1] as RequestInit | undefined)?.headers as Record<string, string> | undefined)?.Authorization;

describe("staff sign-in", () => {
  it("shows the sign-in page for /admin until a staff member signs in", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/login")) return jsonResponse({ token: "tok-123", expires_at: 0, user: { username: "priya", display_name: "Priya S" } });
      if (url.endsWith("/auth/me")) return jsonResponse({ user: { username: "priya", display_name: "Priya S" } });
      return jsonResponse({}, 404);
    });
    renderWithProviders(<App />, "/admin");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "priya" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a-long-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(getStaffToken()).toBe("tok-123"));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Sign in" })).not.toBeInTheDocument());
    expect(window.localStorage.getItem("telecom-agent-name")).toBe("Priya S"); // replies are signed with the account name
    const me = fetchMock.mock.calls.find((c) => String(c[0]).endsWith("/auth/me"));
    expect(me && authHeader(me)).toBe("Bearer tok-123");
  });

  it("shows the error and stays on the sign-in page when the password is wrong", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ error: { code: "INVALID_CREDENTIALS", message: "The username or password is incorrect." } }, 401));
    renderWithProviders(<App />, "/admin");
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "priya" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("incorrect");
    expect(getStaffToken()).toBeNull();
  });

  it("signs out when the server rejects the token", async () => {
    setStaffToken("expired-token");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ error: { code: "SESSION_EXPIRED", message: "Your session has expired. Please sign in again." } }, 401));
    await expect(api.cases()).rejects.toMatchObject({ code: "SESSION_EXPIRED" });
    expect(getStaffToken()).toBeNull();
  });

  it("keeps the customer help center public", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ items: [], total: 0, intents: [], categories: [] }));
    renderWithProviders(<App />, "/");
    expect(screen.queryByRole("heading", { name: "Sign in" })).not.toBeInTheDocument();
  });
});
