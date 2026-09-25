import { useEffect, useMemo, useState } from "react";
import type { HistorySpec, Reading } from "./api";
import { TimeChart, type Series } from "./charts/TimeChart";
import { fmt } from "./format";
import { useLongHistory } from "./hooks";
import { useT, type Key, type Translate } from "./i18n";
import { smooth } from "./lib";
import { useLiveData } from "./live";

const POWER_KEYS = ["pv", "inv", "bat", "socket", "export"] as const;
type PowerKey = (typeof POWER_KEYS)[number];

/** One entry per line in the power chart; `pkey` is what the on/off legend and its localStorage
 * persistence key on, independent of the (translated) label or the Reading field it reads.
 * `lanOnly`: cloud mode never has this field at all (see app/models.py's normalize_cloud) - the
 * line would just always be empty, so it's dropped from the legend entirely in that mode. */
const POWER_DEFS: { pkey: PowerKey; key: keyof Reading; fallback?: keyof Reading; label: Key; color: string; width: number; lanOnly?: boolean }[] = [
  { pkey: "pv", key: "pvPreal", fallback: "pvPow", label: "fl.s.pv", color: "var(--c-pv)", width: 2 },
  { pkey: "inv", key: "invPow", label: "fl.s.inv", color: "var(--c-inv)", width: 1.75 },
  { pkey: "bat", key: "batPreal", fallback: "batPow", label: "fl.s.bat", color: "var(--c-bat)", width: 1.5 },
  { pkey: "socket", key: "offGridPow", label: "fl.s.socket", color: "var(--c-socket)", width: 1.5, lanOnly: true },
  { pkey: "export", key: "exportPow", label: "fl.s.export", color: "var(--c-export)", width: 1.5, lanOnly: true },
];
const meterSeries = (t: Translate): Series[] => [{ key: "meterPow", label: t("fl.s.meter"), color: "var(--c-grid)", width: 1.75 }];
const socSeries = (t: Translate): Series[] => [{ key: "soc", label: t("fl.s.soc"), color: "var(--c-soc)", width: 1.75 }];

// "live" = raw readings from memory; "today"/"yesterday" = the actual local calendar day (not a
// rolling window - they differ from "24h" once it's past midnight); the rest = rolling windows,
// both from 1-minute averages in the bridge's database.
const RANGES: { key: string; label: Key; spec: HistorySpec | null }[] = [
  { key: "live", label: "fl.live", spec: null },
  { key: "today", label: "fl.today", spec: { range: "today" } },
  { key: "yesterday", label: "fl.yesterday", spec: { range: "yesterday" } },
  { key: "6h", label: "fl.6h", spec: { minutes: 360 } },
  { key: "24h", label: "fl.24h", spec: { minutes: 1440 } },
  { key: "7d", label: "fl.7d", spec: { minutes: 10080 } },
  { key: "30d", label: "fl.30d", spec: { minutes: 43200 } },
];

function stored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try { const v = localStorage.getItem(key) as T | null; if (v && allowed.includes(v)) return v; } catch { /* private mode */ }
  return fallback;
}
function remember(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* private mode */ }
}

function loadHiddenPower(): Set<PowerKey> {
  try {
    const raw = localStorage.getItem("flow-hidden")?.split(",") ?? [];
    return new Set(raw.filter((k): k is PowerKey => (POWER_KEYS as readonly string[]).includes(k)));
  } catch { return new Set(); }
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
  const { history, control, mode } = useLiveData();
  const cloudMode = mode === "cloud";
  const POWER_DEFS_SHOWN = POWER_DEFS.filter((p) => !cloudMode || !p.lanOnly);
  const METER = meterSeries(t), SOC = socSeries(t);
  const [range, setRange] = useState(() => stored("flow-range", RANGES.map((r) => r.key), "live"));
  const [smoothOn, setSmoothOn] = useState(() => stored("flow-smooth", ["1", "0"], "1") === "1");
  const [hiddenPower, setHiddenPower] = useState<Set<PowerKey>>(loadHiddenPower);
  const [narrow, setNarrow] = useState(window.innerWidth < 700);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 700);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const togglePower = (pkey: PowerKey) => {
    setHiddenPower((prev) => {
      const next = new Set(prev);
      if (next.has(pkey)) next.delete(pkey); else next.add(pkey);
      remember("flow-hidden", [...next].join(","));
      return next;
    });
  };
  const POWER: Series[] = POWER_DEFS_SHOWN.filter((p) => !hiddenPower.has(p.pkey))
    .map(({ pkey: _pkey, label, ...rest }) => ({ ...rest, label: t(label) }));

  const spec = RANGES.find((r) => r.key === range)!.spec;
  const long = useLongHistory(spec);
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
        <Card title={t("fl.chart.power")} legend={POWER_DEFS_SHOWN.map((p) => (
          <button key={p.pkey} type="button" className={hiddenPower.has(p.pkey) ? "off" : ""}
            aria-pressed={!hiddenPower.has(p.pkey)} title={t("fl.legend.toggle")} onClick={() => togglePower(p.pkey)}>
            <i className="sw" style={{ background: p.color }} />{t(p.label)}
          </button>
        ))}>
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
