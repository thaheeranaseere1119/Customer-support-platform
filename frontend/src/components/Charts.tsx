import { useState } from "react";

export interface StackSeries { key: string; label: string; color: string }

/** Stacked columns (status palette, 2px surface gap, rounded data-end, hover tooltip, legend). */
export function StackedBarChart({ data, series, xKey, height = 220 }:
  { data: Record<string, number | string>[]; series: StackSeries[]; xKey: string; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const pad = { l: 34, r: 8, t: 12, b: 26 };
  const totals = data.map((d) => series.reduce((s, x) => s + Number(d[x.key] || 0), 0));
  const max = Math.max(4, ...totals);
  const ticks = [0, Math.ceil(max / 2), max];
  const band = (width - pad.l - pad.r) / Math.max(1, data.length);
  const bar = Math.min(24, band * 0.6);
  const y = (v: number) => pad.t + (height - pad.t - pad.b) * (1 - v / max);
  return (
    <div style={{ position: "relative" }}>
      <div className="legend" style={{ marginBottom: 8 }}>
        {series.map((s) => <span key={s.key} className="legend-item"><span className="legend-swatch" style={{ background: s.color }} />{s.label}</span>)}
      </div>
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Resolution activity by day and evidence status">
        {ticks.map((t) => (
          <g key={t}><line className="grid-line" x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end">{t}</text></g>
        ))}
        {data.map((d, i) => {
          const cx = pad.l + band * i + band / 2;
          let acc = 0;
          const segs = series.map((s) => {
            const v = Number(d[s.key] || 0);
            const y0 = y(acc);
            acc += v;
            return { s, v, top: y(acc), bottom: y0 };
          }).filter((x) => x.v > 0);
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={cx - band / 2} y={pad.t} width={band} height={height - pad.t - pad.b} fill="transparent" />
              {segs.map((seg, j) => {
                const last = j === segs.length - 1;
                const h = Math.max(0, seg.bottom - seg.top - (last ? 0 : 2));
                return last
                  ? <path key={seg.s.key} fill={seg.s.color} opacity={hover === null || hover === i ? 1 : 0.55}
                      d={`M${cx - bar / 2},${seg.bottom} V${seg.top + 4} Q${cx - bar / 2},${seg.top} ${cx - bar / 2 + 4},${seg.top} H${cx + bar / 2 - 4} Q${cx + bar / 2},${seg.top} ${cx + bar / 2},${seg.top + 4} V${seg.bottom} Z`} />
                  : <rect key={seg.s.key} x={cx - bar / 2} y={seg.top + 2} width={bar} height={h} fill={seg.s.color} opacity={hover === null || hover === i ? 1 : 0.55} />;
              })}
              {(i % 2 === 0 || data.length <= 8) && <text x={cx} y={height - 8} textAnchor="middle">{String(d[xKey]).slice(5)}</text>}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div className="chart-tooltip" style={{ left: `${((pad.l + band * hover + band / 2) / width) * 100}%`, top: 30 }}>
          <b>{String(data[hover][xKey])}</b>
          {series.map((s) => <div key={s.key}>{s.label}: {Number(data[hover][s.key] || 0)}</div>)}
          <div>Total: {totals[hover]}</div>
        </div>
      )}
    </div>
  );
}

/** Single-series horizontal bars: one hue, the title names the series, value labels in text ink. */
export function HorizontalBars({ rows, format = (v: number) => String(v) }: { rows: { label: string; value: number }[]; format?: (v: number) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <p className="small muted">No data yet.</p>;
  return (
    <div role="list">
      {rows.map((r) => (
        <div key={r.label} className="hbar-row" role="listitem" title={`${r.label}: ${format(r.value)}`}>
          <span className="clamp-2 small">{r.label}</span>
          <span className="hbar-track"><span className="hbar-fill" style={{ width: `${(r.value / max) * 100}%` }} /></span>
          <b style={{ textAlign: "right" }}>{format(r.value)}</b>
        </div>
      ))}
    </div>
  );
}
