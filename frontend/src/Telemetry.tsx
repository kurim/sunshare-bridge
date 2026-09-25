import type { Reading } from "./api";
import { SocBar } from "./components/SocBar";
import { fmt } from "./format";
import { useNow } from "./hooks";
import { useT, type Key } from "./i18n";
import { batteryEfficiency, EFF_MIN_KWH, exportW, hms, socketSource } from "./lib";
import { useLiveData } from "./live";

// `lanOnly`: fields cloud mode never has at all (see app/models.py's normalize_cloud) - hidden
// entirely in that mode rather than shown as an always-"–" row, which would look like a fault.
const POWER_ROWS: { key: keyof Reading | "_export" | "_meter"; label: Key; real?: keyof Reading; lanOnly?: boolean }[] = [
  { key: "pvPow", label: "te.p.pvPow", real: "pvPreal" },
  { key: "pv1Pow", label: "te.p.pv1Pow" },
  { key: "pv2Pow", label: "te.p.pv2Pow" },
  { key: "invPow", label: "te.p.invPow" },
  { key: "batPow", label: "te.p.batPow", real: "batPreal" },
  { key: "offGridPow", label: "te.p.offGridPow", lanOnly: true },
  { key: "loadPow", label: "te.p.loadPow" },
  { key: "_export", label: "te.p.export", lanOnly: true },
  { key: "gridPow", label: "te.p.gridPow" },
  { key: "_meter", label: "te.p.meter" },
];

const ENERGY_ROWS: { key: keyof Reading; label: Key; digits: number }[] = [
  { key: "todayEnergyKwh", label: "te.e.todayEnergyKwh", digits: 2 },
  { key: "lifetimeEnergyKwh", label: "te.e.lifetimeEnergyKwh", digits: 2 },
  { key: "pvEnergyTodayKwh", label: "te.e.pvEnergyTodayKwh", digits: 2 },
  { key: "pvEnergyTotalKwh", label: "te.e.pvEnergyTotalKwh", digits: 4 },
  { key: "batChargeEnergyKwh", label: "te.e.batChargeEnergyKwh", digits: 4 },
  { key: "batDischargeEnergyKwh", label: "te.e.batDischargeEnergyKwh", digits: 4 },
];

function Chip({ color, label, value, max }: { color: string; label: string; value: number | null | undefined; max: number }) {
  const pct = value == null ? 0 : Math.min(Math.abs(value) / max * 100, 100);
  return (
    <div className="chip" style={{ ["--c" as string]: color }}>
      <div className="chip-row"><span><i />{label}</span><b>{fmt(value, "W")}</b></div>
      <div className="bar"><div style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

export function Telemetry() {
  const t = useT();
  const { reading, control, mode } = useLiveData();
  const cloudMode = mode === "cloud";
  const now = useNow(1000);
  const r: Reading = reading ?? {};
  const meter = control?.meter_w ?? null;
  const max = Math.max(800, control?.control_max_w ?? 0);
  const eff = batteryEfficiency(reading, control);
  const inv = r.invPow ?? null;
  const load = meter != null && inv != null ? meter + inv : null;
  const age = r._t ? Math.max(0, now - r._t) : null;

  const valueOf = (key: (typeof POWER_ROWS)[number]["key"]): number | null | undefined =>
    key === "_meter" ? meter : key === "_export" ? (r.exportPow ?? exportW(r)) : (r[key] as number | null | undefined);

  const source = socketSource(r);
  const sourceText = source === "unknown" ? "–" : source === "none" ? t("te.src.none") : source === "unclear" ? t("te.src.unclear")
    : source.map((s) => t(`te.src.${s}` as Key)).join(" + ");
  const mqttState = control ? (control.mqtt_connected ? t("cc.diag.connected") : t("cc.diag.disconnected")) : "–";

  return (
    <div className="tele-grid">
      <div className="col">
        <section className="card">
          <div className="card-head">
            <div>
              <h2>{t("te.title")}</h2>
              <p className="hint">
                {t("te.source", { src: r.source ?? "–", time: r._t ? hms(r._t) : "–" })}{age != null ? t("te.ago", { s: fmt(age, "", 0) }) : ""}
              </p>
            </div>
            <span className={`tag ${control ? (control.mqtt_connected ? "ok" : "bad") : ""}`}>{t("te.mqtt", { state: mqttState })}</span>
          </div>
          <div className="chips">
            <Chip color="var(--c-pv)" label={t("te.chip.pv")} value={r.pvPow} max={max} />
            <Chip color="var(--c-inv)" label={t("te.chip.inv")} value={r.invPow} max={max} />
            <Chip color="var(--c-bat)" label={t("te.chip.bat")} value={r.batPow} max={max} />
            {!cloudMode && <Chip color="var(--c-socket)" label={t("te.chip.socket")} value={r.offGridPow} max={max} />}
            <Chip color="var(--c-grid)" label={t("te.chip.grid")} value={meter ?? r.gridPow} max={max} />
          </div>
        </section>

        <section className="card">
          <SocBar soc={r.soc ?? null} settings={control?.settings} />
        </section>

        <section className="card">
          <h2>{t("te.energy")}</h2>
          <div className="rows">
            {ENERGY_ROWS.map((row) => (
              <div key={row.key} className="row">
                <span>{t(row.label)}</span>
                <span className="vv"><b>{fmt(r[row.key] as number | null | undefined, "", row.digits)}</b><span className="unit">kWh</span></span>
              </div>
            ))}
          </div>
        </section>

      </div>
      <div className="col">
        <section className="card">
          <h2>{t("te.power")}</h2>
          <div className="rows">
            {POWER_ROWS.filter((row) => !cloudMode || !row.lanOnly).map((row) => {
              const v = valueOf(row.key);
              const real = row.real ? r[row.real] : null;
              const on = (row.key === "pv1Pow" || row.key === "pv2Pow") && (v ?? 0) > 0;
              return (
                <div key={row.key} className={`row ${on ? "on" : ""}`}>
                  <span>{t(row.label)}</span>
                  <span className="vv">
                    <b>{fmt(v)}</b><span className="unit">W</span>
                    {typeof real === "number" && <span className="hint" title={t("te.realHint")}>({fmt(real)} W)</span>}
                  </span>
                </div>
              );
            })}
          </div>
        </section>

        <section className="card">
          <div className="rows">
            <div className="row"><span>{t("te.selfUse")}</span><b>{load != null && load > 0 && inv != null ? fmt(Math.min(inv / load * 100, 100), "%") : "–"}</b></div>
            <div className="row" title={t("te.eff.title")}>
              <span>{t("te.eff")}</span>
              <b>{!eff ? "–" : eff.pending ? t("te.eff.collecting", { a: fmt(eff.charged, "", 2), b: fmt(EFF_MIN_KWH, "", 2) }) : fmt(eff.pct, "%", 1)}</b>
            </div>
            {!cloudMode && <div className="row"><span>{t("te.socketSource")}</span><b>{sourceText}</b></div>}
            <div className="row"><span>{t("te.mqttMeter")}</span><b>{control ? (control.mqtt_connected ? (control.meter_w != null ? t("te.meter.receiving") : t("te.meter.waiting")) : t("cc.diag.disconnected")) : "–"}</b></div>
            <div className="row"><span>{t("te.meterAge")}</span><b>{control?.meter_age_s != null ? `${control.meter_age_s} s` : "–"}</b></div>
          </div>
        </section>
      </div>
    </div>
  );
}
