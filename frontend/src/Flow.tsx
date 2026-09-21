import { useEffect, useMemo, useState } from "react";
import type { Reading } from "./api";
import { TimeChart, type Series } from "./charts/TimeChart";
import { fmt } from "./format";
import { useLongHistory } from "./hooks";
import { useT, type Key, type Translate } from "./i18n";
import { smooth } from "./lib";
import { useLiveData } from "./live";

const powerSeries = (t: Translate): Series[] => [
  { key: "pvPreal", fallback: "pvPow", label: t("fl.s.pv"), color: "var(--c-pv)", width: 2 },
  { key: "invPow", label: t("fl.s.inv"), color: "var(--c-inv)", width: 1.75 },
  { key: "batPreal", fallback: "batPow", label: t("fl.s.bat"), color: "var(--c-bat)", width: 1.5 },
  { key: "offGridPow", label: t("fl.s.socket"), color: "var(--c-socket)", width: 1.5 },
  { key: "exportPow", label: t("fl.s.export"), color: "var(--c-export)", width: 1.5 },
];
const meterSeries = (t: Translate): Series[] => [{ key: "meterPow", label: t("fl.s.meter"), color: "var(--c-grid)", width: 1.75 }];
const socSeries = (t: Translate): Series[] => [{ key: "soc", label: t("fl.s.soc"), color: "var(--c-soc)", width: 1.75 }];

// "live" = raw readings from memory, the rest = 1-minute averages from the bridge's database.
const RANGES: { key: string; label: Key; minutes: number }[] = [
  { key: "live", label: "fl.live", minutes: 0 },
  { key: "6h", label: "fl.6h", minutes: 360 },
  { key: "24h", label: "fl.24h", minutes: 1440 },
  { key: "7d", label: "fl.7d", minutes: 10080 },
  { key: "30d", label: "fl.30d", minutes: 43200 },
];

function stored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try { const v = localStorage.getItem(key) as T | null; if (v && allowed.includes(v)) return v; } catch { /* private mode */ }
  return fallback;
}
function remember(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* private mode */ }
}

function Card({ title, legend, children }: { title: string; legend: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="card">
      <div className="card-head">
        <span className="label">{title}</span>
        <div className="legend">{legend}</div>
      </div>
      {children}
    </section>
  );
}

export function Flow() {
  const t = useT();
  const { history, control } = useLiveData();
  const POWER = powerSeries(t), METER = meterSeries(t), SOC = socSeries(t);
  const [range, setRange] = useState(() => stored("flow-range", RANGES.map((r) => r.key), "live"));
  const [smoothOn, setSmoothOn] = useState(() => stored("flow-smooth", ["1", "0"], "1") === "1");
  const [narrow, setNarrow] = useState(window.innerWidth < 700);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 700);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const minutes = RANGES.find((r) => r.key === range)!.minutes;
  const long = useLongHistory(minutes);
  const live = range === "live";
  const rows: Reading[] = useMemo(
    () => (live ? (smoothOn ? smooth(history) : history) : long?.rows ?? []),
    [live, smoothOn, history, long],
  );
  const gapSeconds = live ? 60 : (long?.step ?? 60) * 2.5; // longer holes are drawn as breaks

  const s = control?.settings;
  const refs = s
    ? [{ value: Number(s.NIGHT_MIN_SOC), color: "var(--c-ref-min)" }, { value: Number(s.CHARGE_FULL_SOC), color: "var(--c-ref-full)" }]
    : [];

  let spanText = "–";
  if (rows.length > 1) {
    const min = ((rows[rows.length - 1]._t ?? 0) - (rows[0]._t ?? 0)) / 60;
    const span = min >= 2880 ? t("fl.days", { n: fmt(min / 1440, "", 1) }) : min >= 90 ? fmt(min / 60, "h", 1) : fmt(min, "min");
    spanText = live ? t("fl.span.live", { span }) : t("fl.span.hist", { span, step: fmt((long?.step ?? 60) / 60, "min") });
  }

  const empty = live ? t("fl.empty.live")
    : long && long.enabled === false ? t("fl.empty.disabled")
    : long ? t("fl.empty.notEnough") : t("fl.empty.loading");
  const hasData = rows.length >= 2;
  // Wide: the power chart matches the two stacked charts next to it.
  const hPower = narrow ? 240 : 440, hSide = narrow ? 160 : 180;
  const chart = (series: Series[], height: number, unit: string, label: string, extra: object = {}) =>
    hasData
      ? <TimeChart data={rows} series={series} height={height} unit={unit} label={label} gapSeconds={gapSeconds} {...extra} />
      : <p className="hint chart-empty">{empty}</p>;

  return (
    <>
      <section className="card">
        <div className="card-head">
          <div><h2>{t("fl.title")}</h2><p className="hint">{t("fl.subtitle")}</p></div>
          <span className="tag info">{spanText}</span>
        </div>
        <div className="ranges" role="group" aria-label={t("fl.range")}>
          {RANGES.map((r) => (
            <button key={r.key} type="button" aria-pressed={range === r.key}
              onClick={() => { setRange(r.key); remember("flow-range", r.key); }}>{t(r.label)}</button>
          ))}
          <button type="button" className="smooth" aria-pressed={smoothOn && live} disabled={!live}
            title={t("fl.smooth.title")}
            onClick={() => { setSmoothOn(!smoothOn); remember("flow-smooth", smoothOn ? "0" : "1"); }}>{t("fl.smooth")}</button>
        </div>
      </section>

      <div className="flow-grid">
        <Card title={t("fl.chart.power")} legend={POWER.map((p) => <span key={p.label}><i className="sw" style={{ background: p.color }} />{p.label}</span>)}>
          {chart(POWER, hPower, "W", t("fl.aria.power"))}
        </Card>
        <div className="flow-side">
          <Card title={t("fl.chart.meter")} legend={<span>{t("fl.legend.meter")}</span>}>
            {chart(METER, hSide, "W", t("fl.aria.meter"))}
          </Card>
          <Card title={t("fl.chart.soc")} legend={<><span><i className="sw bad" />{t("fl.legend.min")}</span><span><i className="sw ok" />{t("fl.legend.full")}</span></>}>
            {chart(SOC, hSide, "%", t("fl.aria.soc"), { min: 0, max: 100, step: 25, refs })}
          </Card>
        </div>
      </div>
    </>
  );
}
