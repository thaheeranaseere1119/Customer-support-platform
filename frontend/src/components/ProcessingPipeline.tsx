import { STAGES, type StageState } from "../hooks/useResolution";
import { Icon } from "./Icon";

const STAGE_ICONS = ["brain", "layers", "search", "chart", "shield", "sparkle", "link", "check"];

export function ProcessingPipeline({ stages }: { stages: StageState }) {
  return (
    <ol className="pipeline" aria-label="AI processing pipeline" style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {STAGES.map((stage, i) => {
        const state = stages[stage.name];
        const done = ["success", "warning"].includes(state.status);
        const icon = state.status === "running" ? "refresh" : state.status === "error" ? "x" : done ? (state.status === "warning" ? "alert" : "check") : STAGE_ICONS[i];
        return (
          <li key={stage.name} className={`pipe-step ${state.status} ${done ? "done" : ""}`} title={state.detail || stage.label}>
            <span className="pipe-icon"><Icon name={icon} size={18} className={state.status === "running" ? "spin" : undefined} /></span>
            <span className="pipe-label">{i + 1}. {stage.label}</span>
            <span className="pipe-detail">{state.status === "running" ? "working…" : state.duration_ms !== undefined ? `${Math.round(state.duration_ms)} ms` : state.status === "error" ? "failed" : ""}</span>
            <span className="sr-only">{state.status}</span>
          </li>
        );
      })}
    </ol>
  );
}
