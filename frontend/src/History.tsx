import { useEffect, useMemo, useState } from "react";
import { getDay, getDays, type DayDetail, type DayList, type DaySummary } from "./api";
import { TimeChart, type Series } from "./charts/TimeChart";
import { Icon, type IconName } from "./components/Icons";
import { ForecastChart } from "./components/PvForecast";
import { fmt } from "./format";
import { LANGUAGES, useI18n, useT, type Key } from "./i18n";
import { actualSeries, forecastResult, hm, monthTotal, type ForecastResult } from "./lib";
import { useLiveData } from "./live";

const RESULT: Record<ForecastResult, { icon: IconName; color: string; label: Key }> = {
  hit: { icon: "check", color: "var(--ok)", label: "hi.res.hit" },
  over: { icon: "arrowUp", color: "var(--info)", label: "hi.res.over" },
  under: { icon: "arrowDown", color: "var(--bad)", label: "hi.res.under" },
};

const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
// noon, so a DST switch never moves the date
const dateOf = (day: string) => new Date(`${day}T12:00:00`);

/** Today is still running, so it gets no verdict yet. */
const resultOf = (d: DaySummary) => (d.day === todayIso() ? null : forecastResult(d.pv_kwh, d.fc_kwh));

function DayButton({ d, selected, onPick }: { d: DaySummary; selected: boolean; onPick: () => void }) {
  const t = useT();
  const { lang } = useI18n();
  const res = resultOf(d);
  const date = dateOf(d.day);
  return (
    <button type="button" className="day" aria-pressed={selected} onClick={onPick}
      style={res ? { ["--day-c" as string]: RESULT[res].color } : undefined}
      title={res ? t(RESULT[res].label) : d.day === todayIso() ? t("hi.res.running") : t("hi.res.none")}>
      <span className="day-date">{date.toLocaleDateString(LANGUAGES[lang].tag, { weekday: "short", day: "2-digit", month: "2-digit" })}</span>
      <span className="day-val">
        {res ? <Icon name={RESULT[res].icon} /> : <span className="icon" />}
        {fmt(d.pv_kwh, "kWh", 1)}
      </span>
    </button>
  );
}

function Tile({ label, icon, color, value, hint }: { label: string; icon: IconName; color: string; value: string; hint?: string }) {
  return (
    <div className="tile" style={{ ["--tile-c" as string]: color }}>
      <div className="tile-head"><span className="label with-icon"><Icon name={icon} />{label}</span></div>
      <strong>{value}</strong>
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

export function History() {
  const t = useT();
  const { lang } = useI18n();
  const { control } = useLiveData();
  const [list, setList] = useState<DayList | null>(null);
  const [failed, setFailed] = useState(false);
  const [day, setDay] = useState<string | null>(null);
  const [detail, setDetail] = useState<DayDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => getDays().then((l) => { if (!cancelled) { setList(l); setFailed(false); } }).catch(() => { if (!cancelled) setFailed(true); });
    load();
    const id = setInterval(() => { if (!document.hidden) load(); }, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // newest first, like the days
  const months = useMemo(() => [...new Set((list?.days ?? []).map((d) => d.day.slice(0, 7)))], [list]);
  const [month, setMonth] = useState<string | null>(null);
  const shownMonth = month && months.includes(month) ? month : months[0] ?? null;
  const monthIdx = shownMonth ? months.indexOf(shownMonth) : -1;
  const monthDays = useMemo(() => (list?.days ?? []).filter((d) => d.day.startsWith(shownMonth ?? "-")), [list, shownMonth]);
  const total = monthTotal(monthDays);
  const shown = day && day.startsWith(shownMonth ?? "-") ? day : monthDays[0]?.day ?? null;
  useEffect(() => {
    setDetail(null);
    if (!shown) return;
    let cancelled = false;
    const load = () => getDay(shown).then((d) => { if (!cancelled) setDetail(d); }).catch(() => undefined);
    load();
    const id = setInterval(() => { if (!document.hidden && shown === todayIso()) load(); }, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [shown]);

  const rows = detail?.history.rows ?? [];
  const actual = useMemo(() => actualSeries(rows), [rows]);
  const gapSeconds = (detail?.history.step ?? 60) * 2.5;
  const power: Series[] = [
    { key: "pvPreal", fallback: "pvPow", label: t("fl.s.pv"), color: "var(--c-pv)", width: 2 },
    { key: "invPow", label: t("fl.s.inv"), color: "var(--c-inv)", width: 1.75 },
    { key: "batPreal", fallback: "batPow", label: t("fl.s.bat"), color: "var(--c-bat)", width: 1.5 },
  ];
  const s = control?.settings;
  const refs = s
    ? [{ value: Number(s.NIGHT_MIN_SOC), color: "var(--c-ref-min)" }, { value: Number(s.CHARGE_FULL_SOC), color: "var(--c-ref-full)" }]
    : [];

  const res = detail ? resultOf(detail) : null;
  const running = detail?.day === todayIso();
  const diff = res && detail?.pv_kwh != null && detail.fc_kwh ? (detail.pv_kwh / detail.fc_kwh - 1) * 100 : null;

  return (
    <>
      <section className="card">
        <h2>{t("hi.title")}</h2>
        <p className="hint">{t("hi.subtitle")}</p>
        {failed && <p className="error" role="alert">{t("hi.failed")}</p>}
        {list && !list.enabled && <p className="hint">{t("fl.empty.disabled")}</p>}
        {list?.enabled && !list.days.length && <p className="hint">{t("hi.empty")}</p>}
        {shownMonth && (
          <>
            <div className="month-nav">
              <button type="button" className="link with-icon" disabled={monthIdx >= months.length - 1}
                onClick={() => setMonth(months[monthIdx + 1])} aria-label={t("hi.prevMonth")}>‹</button>
              <h3>{dateOf(`${shownMonth}-01`).toLocaleDateString(LANGUAGES[lang].tag, { month: "long", year: "numeric" })}</h3>
              <button type="button" className="link with-icon" disabled={monthIdx <= 0}
                onClick={() => setMonth(months[monthIdx - 1])} aria-label={t("hi.nextMonth")}>›</button>
            </div>
            <p className="month-total">
              {t("hi.month.reached", { kwh: fmt(total.pvKwh, "kWh", 1) })}
              {" · "}
              {total.fcDays ? t("hi.month.expected", { kwh: fmt(total.fcKwh, "kWh", 1) }) : t("hi.month.noForecast")}
              {total.fcDays > 0 && total.fcDays < total.days && <span className="hint"> ({t("hi.month.coverage", { n: total.fcDays, of: total.days })})</span>}
            </p>
            <div className="day-list" role="group" aria-label={t("hi.pick")}>
              {monthDays.map((d) => <DayButton key={d.day} d={d} selected={d.day === shown} onPick={() => setDay(d.day)} />)}
            </div>
            <div className="legend day-legend">
              {(Object.keys(RESULT) as ForecastResult[]).map((k) => (
                <span key={k} className="with-icon" style={{ color: RESULT[k].color }}><Icon name={RESULT[k].icon} />{t(RESULT[k].label)}</span>
              ))}
            </div>
          </>
        )}
      </section>

      {shown && (
        <>
          <h2 className="day-title">{dateOf(shown).toLocaleDateString(LANGUAGES[lang].tag, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</h2>
          {detail && (
            <div className="tiles">
              <Tile label={t("hi.yield")} icon="sun" color="var(--c-pv)" value={fmt(detail.pv_kwh, "kWh", 1)} />
              <Tile label={t("hi.forecast")} icon={res ? RESULT[res].icon : "cloud"} color={res ? RESULT[res].color : "var(--muted)"}
                value={fmt(detail.fc_kwh, "kWh", 1)}
                hint={detail.fc_kwh == null ? t("hi.noForecast")
                  : res && diff != null ? `${t(RESULT[res].label)} · ${diff > 0 ? "+" : ""}${fmt(diff, "%")}`
                  : running ? t("hi.res.running") : undefined} />
              <Tile label={t("hi.full")} icon="battery" color={detail.full_at != null ? "var(--ok)" : "var(--muted)"}
                value={detail.full_at != null ? hm(detail.full_at) : "–"}
                hint={detail.full_at != null ? t("hi.fullAt") : running ? t("hi.notFullYet") : t("hi.notFull")} />
            </div>
          )}
          <div className="flow-grid">
            <section className="card">
              <div className="card-head">
                <span className="label">{t("fl.chart.power")}</span>
                <div className="legend">{power.map((p) => <span key={p.key}><i className="sw" style={{ background: p.color }} />{p.label}</span>)}</div>
              </div>
              {rows.length >= 2
                ? <TimeChart data={rows} series={power} height={240} unit="W" label={t("fl.aria.power")} gapSeconds={gapSeconds} />
                : <p className="hint chart-empty">{detail ? t("hi.noSamples") : t("fl.empty.loading")}</p>}
            </section>
            <section className="card">
              <div className="card-head"><span className="label">{t("fl.chart.soc")}</span></div>
              {rows.length >= 2
                ? <TimeChart data={rows} series={[{ key: "soc", label: t("fl.s.soc"), color: "var(--c-soc)", width: 1.75 }]} height={180}
                    unit="%" label={t("fl.aria.soc")} gapSeconds={gapSeconds} min={0} max={100} step={25} refs={refs} />
                : <p className="hint chart-empty">{detail ? t("hi.noSamples") : t("fl.empty.loading")}</p>}
            </section>
          </div>
          {detail && detail.fc_series.length > 1 && (
            <section className="card">
              <div className="card-head">
                <span className="label with-icon"><Icon name="sun" />{t("ov.pvf")}</span>
                <div className="legend">
                  <span><i className="sw" style={{ background: "var(--c-pv)" }} />{t("ov.pvf.legendForecast")}</span>
                  <span><i className="sw" style={{ background: "var(--c-inv)" }} />{t("ov.pvf.legendActual")}</span>
                </div>
              </div>
              <ForecastChart series={detail.fc_series} actual={actual} stepS={detail.fc_series[1][0] - detail.fc_series[0][0]} label={t("hi.aria.forecast")} height={180} />
            </section>
          )}
        </>
      )}
    </>
  );
}
