import { describe, expect, it } from "vitest";
import { linesToList, pct, splitCitations } from "../utils/format";

describe("format utils", () => {
  it("splits text into plain parts and citation ids without HTML", () => {
    const parts = splitCitations("Check the router. [KB-031] Then wait [DEMO-TKT-000001].");
    expect(parts).toEqual([
      { kind: "text", value: "Check the router. " }, { kind: "cite", id: "KB-031" },
      { kind: "text", value: " Then wait " }, { kind: "cite", id: "DEMO-TKT-000001" }, { kind: "text", value: "." },
    ]);
  });
  it("formats percentages and handles missing values", () => {
    expect(pct(0.925)).toBe("93%");
    expect(pct(null)).toBe("—");
  });
  it("turns multiline text into a clean list", () => {
    expect(linesToList(" a \n\n b\n")).toEqual(["a", "b"]);
  });
});

describe("help article parsing", () => {
  it("shows customers the customer steps, never the agent instructions", async () => {
    const { parseArticle } = await import("../site/articles");
    const content = "Symptoms: No signal.\nAlso asked as: no bars on my phone\nResolution steps:\n1. Restart the device.\n"
      + "2. Escalate with location details.\nCustomer steps:\n1. Restart your phone.\n2. Tell me where you are.\n"
      + "Escalate when: No signal persists.\nCaution: None.";
    expect(parseArticle(content)).toEqual({ symptoms: "No signal.", steps: ["Restart your phone.", "Tell me where you are."] });
  });

  it("falls back to the resolution steps when an article has no customer wording", async () => {
    const { parseArticle } = await import("../site/articles");
    expect(parseArticle("Symptoms: x\nResolution steps:\n1. Restart the router.\nCaution: y").steps).toEqual(["Restart the router."]);
  });
});
