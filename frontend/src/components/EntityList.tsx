import type { Entity } from "../types/api";
import { humanize } from "../utils/format";

export function EntityList({ entities, memory = [] }: { entities: Entity[]; memory?: Entity[] }) {
  if (!entities.length && !memory.length) return <span className="small muted">No entities detected.</span>;
  return (
    <div className="entity-list">
      {entities.map((e, i) => (
        <span key={`e${i}`} className="entity"><span className="etype">{humanize(e.type)}</span><span className="evalue">{e.value}</span></span>
      ))}
      {memory.map((e, i) => (
        <span key={`m${i}`} className="entity memory" title="Carried over from conversation memory">
          <span className="etype">Memory · {humanize(e.type)}</span><span className="evalue">{e.value}</span>
        </span>
      ))}
    </div>
  );
}
