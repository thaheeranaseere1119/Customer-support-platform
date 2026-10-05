import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Score } from "../pages/AnalyticsPage";

describe("evaluation scores", () => {
  it("shows a perfect score on a small sample as its 95% lower bound, never as 100%", () => {
    const { container } = render(<Score label="Accuracy" value={1} ci={{ successes: 8, total: 8, lower_95: 0.6756 }} />);
    expect(screen.getByText("≥ 68%")).toBeInTheDocument();
    expect(screen.getByText("8/8 correct · 95% lower bound")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/100(\.0)?%/);
  });

  it("headlines an imperfect score the same way, so a better result never looks worse", () => {
    render(<Score label="Accuracy" value={0.925} ci={{ successes: 37, total: 40, lower_95: 0.80 }} />);
    expect(screen.getByText("≥ 80%")).toBeInTheDocument();
    expect(screen.getByText("37/40 correct · measured 92.5% · 95% lower bound")).toBeInTheDocument();
  });

  it("orders 8/8 above 6/8", () => {
    const { container: perfect } = render(<Score label="A" value={1} ci={{ successes: 8, total: 8, lower_95: 0.6756 }} />);
    const { container: lower } = render(<Score label="B" value={0.75} ci={{ successes: 6, total: 8, lower_95: 0.4093 }} />);
    expect(perfect.textContent).toContain("≥ 68%");
    expect(lower.textContent).toContain("≥ 41%");
  });

  it("uses decimals for ranking scores", () => {
    render(<Score label="MRR" value={1} ci={{ successes: 40, total: 40, lower_95: 0.9124 }} decimals noun="ranked first" />);
    expect(screen.getByText("≥ 0.91")).toBeInTheDocument();
  });
});
