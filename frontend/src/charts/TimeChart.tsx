import { useMemo, useState, type PointerEvent } from "react";
import type { Reading } from "../api";
import { fmt } from "../format";
import { useWidth } from "../hooks";
import { dhm, dm, hm, hms } from "../lib";

export interface Series {
  key: keyof Reading;
  label: string;
  color: string;
  width?: number;
  /** Used where `key` has no value (e.g. the real PV value, else the booked one). */
  fallback?: keyof Reading;
}

interface Props {
  data: Reading[];
  series: Series[];
  height: number;
  unit: string;
  label: string;
  /** Fixed axis (e.g. 0-100 %); otherwise it follows the data from 0. */
  min?: number;
  max?: number;
  step?: number;
  refs?: { value: number; color: string }[];
  /** Holes longer than this many seconds are drawn as breaks. */
  gapSeconds: number;
}

const L = 42, R = 12, T = 8, B = 22;

function niceStep(range: number, n: number): number {
  const raw = range / n;
  const pow = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * pow >= raw) return m * pow;
  return 10 * pow;
}

/** Index of the sample closest to time t (data sorted by _t). */
function nearest(data: Reading[], t: number): number {
  let lo = 0, hi = data.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if ((data[m]._t ?? 0) < t) lo = m; else hi = m; }
  return Math.abs((data[lo]._t ?? 0) - t) <= Math.abs((data[hi]._t ?? 0) - t) ? lo : hi;
}

export function TimeChart({ data, series, height, unit, label, min, max, step, refs = [], gapSeconds }: Props) {
  const [box, width] = useWidth<HTMLDivElement>();
  const [hoverT, setHoverT] = useState<number | null>(null); // time, not index: live data keeps shifting
  const W = Math.max(240, width), H = height;

  const value = (p: Reading, s: Series): number | null => {
    const v = p[s.key] ?? (s.fallback ? p[s.fallback] : null);
    return typeof v === "number" ? v : null;
  };

  const g = useMemo(() => {
    const tMin = data[0]?._t ?? 0, tMax = data[data.length - 1]?._t ?? 1;
    const span = Math.max(tMax - tMin, 1);
    let lo = min, hi = max, tick = step;
    if (lo === undefined || hi === undefined || tick === undefined) {
      lo = 0; hi = 0;
      for (const p of data) for (const s of series) {
        const v = p[s.key] ?? (s.fallback ? p[s.fallback] : null);
        if (typeof v === "number") { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      }
      tick = niceStep(Math.max(hi - lo, 40), H > 250 ? 6 : 4);
      lo = Math.floor(lo / tick) * tick;
      hi = Math.ceil(hi / tick) * tick;
      if (hi === lo) hi = lo + tick;
    }
    return { tMin, span, lo, hi, tick };
  }, [data, series, min, max, step, H]);

  const x = (t: number) => L + (t - g.tMin) / g.span * (W - L - R);
  const y = (v: number) => T + (g.hi - v) / (g.hi - g.lo) * (H - T - B);

  const paths = useMemo(() => series.map((s) => {
    let d = "", prevT: number | null = null;
    for (const p of data) {
      const raw = p[s.key] ?? (s.fallback ? p[s.fallback] : null);
      if (typeof raw !== "number" || p._t == null) continue;
      d += `${d && prevT != null && p._t - prevT <= gapSeconds ? "L" : "M"}${x(p._t).toFixed(1)} ${y(raw).toFixed(1)}`;
      prevT = p._t;
    }
    return d;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [data, series, gapSeconds, g, W, H]);

  const ticks: number[] = [];
  for (let v = g.lo; v <= g.hi + 1e-9; v += g.tick) ticks.push(Math.round(v * 1000) / 1000);
  const nT = W > 700 ? 6 : W > 420 ? 4 : 3;
  const wide = g.span > 36 * 3600;
  // Several days: the axis shows dates only (time + date would overlap), the tooltip both.
  const fmtAxis = g.span > 3 * 86400 ? dm : wide ? dhm : hm, fmtTip = wide ? dhm : hms;

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width * W;
    setHoverT(g.tMin + (px - L) / (W - L - R) * g.span);
  };

  const p = hoverT != null && data.length ? data[nearest(data, hoverT)] : undefined;
  const px = p?._t != null ? x(p._t) : 0;
  // Anchored to the side away from the cursor, so it always stays inside the chart.
  const tipSide = px > W / 2 ? { left: L + 6 } : { right: R + 6 };

  return (
    <div className="chart" ref={box}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={label}
        style={{ touchAction: "pan-y" }} onPointerMove={onMove} onPointerLeave={() => setHoverT(null)} onPointerCancel={() => setHoverT(null)}>
        {ticks.map((v) => (
          <g key={v}>
            <line className={v === 0 ? "grid zero" : "grid"} x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
            <text className="axis" x={L - 6} y={y(v) + 3} textAnchor="end">{v}</text>
          </g>
        ))}
        {Array.from({ length: nT + 1 }, (_, i) => {
          const t = g.tMin + g.span * i / nT;
          return <text key={i} className="axis" x={x(t)} y={H - 6} textAnchor={i === 0 ? "start" : i === nT ? "end" : "middle"}>{fmtAxis(t)}</text>;
        })}
        {refs.map((r) => <line key={r.value} className="ref" x1={L} x2={W - R} y1={y(r.value)} y2={y(r.value)} style={{ stroke: r.color }} />)}
        {series.map((s, i) => paths[i] && <path key={String(s.key)} d={paths[i]} fill="none" style={{ stroke: s.color }} strokeWidth={s.width ?? 1.5} strokeLinejoin="round" strokeLinecap="round" />)}
        {p && (
          <g pointerEvents="none">
            <line className="cursor" x1={px} x2={px} y1={T} y2={H - B} />
            {series.map((s) => { const v = value(p, s); return v == null ? null : <circle key={String(s.key)} cx={px} cy={y(v)} r={3} style={{ fill: s.color }} />; })}
          </g>
        )}
      </svg>
      {p && p._t != null && (
        <div className="tip" style={tipSide}>
          <b>{fmtTip(p._t)}</b>
          {series.map((s) => (
            <div key={String(s.key)}><span style={{ color: s.color }}>●</span> {s.label} <b>{fmt(value(p, s))}</b> {unit}</div>
          ))}
        </div>
      )}
    </div>
  );
}
