import { useMemo, useState, type PointerEvent } from "react";
import type { PvForecast, PvForecastDay } from "../api";
import { fmt } from "../format";
import { useLongHistory, useNow, useWidth } from "../hooks";
import { useMsg, useT } from "../i18n";
import { actualSeries, dm, hm } from "../lib";
import { Icon } from "./Icons";

const H = 120, L = 34, R = 8, T = 8, B = 20;
const ACTUAL_GAP_S = 300; // a longer hole in the history is drawn as a break, and no tooltip value is taken across it

function niceMax(w: number): number {
  for (const step of [200, 400, 500, 1000, 2000]) if (w <= step * 4) return Math.ceil(Math.max(w, 1) / step) * step;
  return Math.ceil(w / 1000) * 1000;
}

/** Expected PV power over today and tomorrow (see app/pvforecast.py); the bridge sends the whole
 * curve, so nothing is asked of pvnode when this is drawn or when "now" moves. */
function ForecastChart({ series, actual, stepS, label }: { series: [number, number][]; actual: [number, number][]; stepS: number; label: string }) {
  const t = useT();
  const now = useNow(60_000);
  const [box, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const W = Math.max(240, width);

  const g = useMemo(() => {
    const t0 = series[0][0], t1 = series[series.length - 1][0] + stepS;
    const peak = Math.max(...series.map((p) => p[1]), ...actual.map((p) => p[1]));
    const midnight = new Date(now * 1000);
    midnight.setHours(24, 0, 0, 0);
    return { t0, t1, hi: niceMax(peak), midnight: midnight.getTime() / 1000 };
  }, [series, actual, stepS, now]);

  const x = (ts: number) => L + (ts - g.t0) / (g.t1 - g.t0) * (W - L - R);
  const y = (w: number) => T + (1 - w / g.hi) * (H - T - B);

  const area = (pts: [number, number][]) => {
    if (!pts.length) return "";
    const line = pts.map(([ts, w]) => `L${x(ts).toFixed(1)} ${y(w).toFixed(1)}`).join("");
    return `M${x(pts[0][0]).toFixed(1)} ${y(0)}${line}L${x(pts[pts.length - 1][0]).toFixed(1)} ${y(0)}Z`;
  };
  // what was reached: one filled area per continuous stretch of history
  const actualArea = actual.filter((p) => p[0] >= g.t0 && p[0] <= g.t1).reduce<[number, number][][]>((runs, p) => {
    const run = runs[runs.length - 1];
    if (run && p[0] - run[run.length - 1][0] <= ACTUAL_GAP_S) run.push(p); else runs.push([p]);
    return runs;
  }, []).map((run) => (run.length > 1 ? area(run) : "")).join("");
  const todayPts = series.filter((p) => p[0] < g.midnight);
  const tomorrowPts = series.filter((p) => p[0] >= g.midnight);

  // 6-hourly axis labels, the local midnight carries the date
  const ticks: number[] = [];
  const first = new Date(g.t0 * 1000);
  first.setHours(Math.ceil(first.getHours() / 6) * 6, 0, 0, 0);
  for (let ts = first.getTime() / 1000; ts <= g.t1; ts += 6 * 3600) ticks.push(ts);
  const yTicks = [0, g.hi / 2, g.hi];

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setHover(g.t0 + ((e.clientX - rect.left) / rect.width * W - L) / (W - L - R) * (g.t1 - g.t0));
  };
  const point = hover != null ? series.reduce((a, b) => (Math.abs(b[0] - hover) < Math.abs(a[0] - hover) ? b : a)) : null;
  const px = point ? x(point[0]) : 0;
  const reached = hover != null && actual.length
    ? actual.reduce((a, b) => (Math.abs(b[0] - hover) < Math.abs(a[0] - hover) ? b : a)) : null;
  const reachedW = reached && point && Math.abs(reached[0] - point[0]) <= ACTUAL_GAP_S ? reached[1] : null;

  return (
    <div className="chart" ref={box}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={label}
        style={{ touchAction: "pan-y" }} onPointerMove={onMove} onPointerLeave={() => setHover(null)} onPointerCancel={() => setHover(null)}>
        {yTicks.map((v) => (
          <g key={v}>
            <line className={v === 0 ? "grid zero" : "grid"} x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
            <text className="axis" x={L - 6} y={y(v) + 3} textAnchor="end">{v}</text>
          </g>
        ))}
        {ticks.map((ts) => (
          <text key={ts} className="axis" x={x(ts)} y={H - 6} textAnchor="middle">{new Date(ts * 1000).getHours() === 0 ? dm(ts) : hm(ts)}</text>
        ))}
        <path d={area(todayPts)} style={{ fill: "var(--c-pv)", stroke: "var(--c-pv)" }} fillOpacity={0.35} strokeWidth={1.5} strokeLinejoin="round" />
        <path d={area(tomorrowPts)} style={{ fill: "var(--c-pv)", stroke: "var(--c-pv)" }} fillOpacity={0.15} strokeWidth={1.5} strokeOpacity={0.6} strokeLinejoin="round" />
        <path d={actualArea} style={{ fill: "var(--c-inv)", stroke: "var(--c-inv)" }} fillOpacity={0.35} strokeWidth={1.5} strokeLinejoin="round" />
        {now >= g.t0 && now <= g.t1 && (
          <g pointerEvents="none">
            <line className="cursor" x1={x(now)} x2={x(now)} y1={T} y2={H - B} />
            <text className="axis" x={x(now)} y={T + 8} textAnchor={x(now) > W / 2 ? "end" : "start"} dx={x(now) > W / 2 ? -4 : 4}>{t("ov.pvf.now")}</text>
          </g>
        )}
        {point && (
          <g pointerEvents="none">
            <line className="cursor" x1={px} x2={px} y1={T} y2={H - B} />
            <circle cx={px} cy={y(point[1])} r={3} style={{ fill: "var(--c-pv)" }} />
          </g>
        )}
      </svg>
      {point && (
        <div className="tip" style={px > W / 2 ? { left: L + 6 } : { right: R + 6 }}>
          <b>{dm(point[0])} {hm(point[0])}</b>
          <div><span style={{ color: "var(--c-pv)" }}>●</span> {t("ov.pvf.tip", { w: fmt(point[1], "W") })}</div>
          {reachedW != null && <div><span style={{ color: "var(--c-inv)" }}>●</span> {t("ov.pvf.tipActual", { w: fmt(reachedW, "W") })}</div>}
        </div>
      )}
    </div>
  );
}

function DayTile({ label, day, hint }: { label: string; day: PvForecastDay; hint?: string }) {
  const t = useT();
  return (
    <div className="tile" style={{ ["--tile-c" as string]: "var(--c-pv)" }}>
      <div className="tile-head"><span className="label with-icon"><Icon name="sun" />{label}</span></div>
      <strong>{fmt(day.kwh, "kWh", 1)}</strong>
      <span className="hint">{hint ?? t("ov.pvf.peak", { w: fmt(day.peak_w, "W"), time: hm(day.peak_t) })}</span>
    </div>
  );
}

/** `actualKwh` is the bridge's own PV yield of today (booked PV power, integrated), so the forecast
 * can be read against what has already happened. */
export function PvForecastCard({ forecast, actualKwh }: { forecast: PvForecast; actualKwh: number | null }) {
  const t = useT();
  const tm = useMsg();
  const history = useLongHistory({ range: "today" });
  const actual = useMemo(() => actualSeries(history?.rows), [history]);
  const { today, tomorrow, series, updated_at: updatedAt, error } = forecast;
  const rest = today?.remaining_kwh != null ? fmt(today.remaining_kwh, "kWh", 1) : null;
  const todayHint = rest == null ? undefined
    : actualKwh != null ? t("ov.pvf.todayDetail", { actual: fmt(actualKwh, "kWh", 1), rest }) : t("ov.pvf.todayRest", { rest });
  return (
    <section className="card">
      <h2 className="with-icon"><Icon name="sun" />{t("ov.pvf")}</h2>
      {(today || tomorrow) && (
        <div className="tiles compact">
          {today && <DayTile label={t("ov.pvf.today")} day={today} hint={todayHint} />}
          {tomorrow && <DayTile label={t("ov.pvf.tomorrow")} day={tomorrow} />}
        </div>
      )}
      {series.length > 1 && <ForecastChart series={series} actual={actual} stepS={forecast.step_s} label={t("ov.pvf.chart")} />}
      {series.length > 1 && (
        <div className="legend">
          <span><i className="sw" style={{ background: "var(--c-pv)" }} />{t("ov.pvf.legendForecast")}</span>
          <span><i className="sw" style={{ background: "var(--c-inv)" }} />{t("ov.pvf.legendActual")}</span>
        </div>
      )}
      {error && <p className="hint" role="alert">{tm(error)}</p>}
      {updatedAt != null && <p className="hint">{t("ov.pvf.updated", { time: hm(updatedAt) })}</p>}
    </section>
  );
}
