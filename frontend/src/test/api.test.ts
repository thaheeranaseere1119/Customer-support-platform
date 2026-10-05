import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../services/api";
import { jsonResponse } from "./render";

afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("converts structured backend errors into ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ error: { code: "NOT_FOUND", message: "Case X not found", request_id: "req_1" } }, 404));
    await expect(api.caseDetail("X")).rejects.toMatchObject({ code: "NOT_FOUND", status: 404, requestId: "req_1" });
  });

  it("treats a non-JSON gateway error as the backend being unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, status: 500, json: async () => { throw new SyntaxError("bad"); } } as unknown as Response);
    await expect(api.health()).rejects.toMatchObject({ code: "BACKEND_UNAVAILABLE" });
  });

  it("reports network failures with a friendly message", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const error = await api.health().catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("NETWORK_ERROR");
    expect(error.message).toMatch(/couldn't reach the server/);
  });
});
