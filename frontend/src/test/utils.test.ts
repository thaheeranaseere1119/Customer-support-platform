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
