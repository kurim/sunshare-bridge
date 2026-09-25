import type { ReactNode } from "react";
import type { WeatherDay } from "./api";
import { EnergyFlow } from "./components/EnergyFlow";
import { BatteryIcon, Icon } from "./components/Icons";
import { fmt } from "./format";
import { useMsg, useT, type Key, type Translate } from "./i18n";
import { socColor } from "./lib";
import { useLiveData } from "./live";

/** `color` is one of the chart series colors, so a value is recognisable across pages. `badge` sits at the right of the label. */
function Tile({ label, value, hint, icon, color, badge }: {
  label: string; value: string; hint?: string; icon: ReactNode; color: string; badge?: ReactNode;
}) {
  return (
    <div className="tile" style={{ ["--tile-c" as string]: color }}>
      <div className="tile-head">
        <span className="label with-icon">{icon}{label}</span>
        {badge}
      </div>
      <strong>{value}</strong>
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

/** One day of the OpenWeatherMap outlook (see app/weather.py) - informational only, it never
 * changes the battery plan; the user decides for themselves whether to raise NIGHT_MIN_SOC or
 * CHARGE_RESERVE_W ahead of a bad day. */
function WeatherTile({ t, label, day }: { t: Translate; label: string; day: WeatherDay }) {
  return (
    <div className="tile" style={{ ["--tile-c" as string]: "var(--c-grid)" }}>
      <div className="tile-head">
        <span className="label with-icon"><Icon name={day.outlook === "sunny" ? "sun" : "cloud"} />{label}</span>
      </div>
      <strong>{t(`ov.weather.outlook.${day.outlook}` as Key)}</strong>
      <span className="hint">{t("ov.weather.detail", { clouds: fmt(day.clouds_pct, "%"), pop: fmt(day.pop_pct, "%") })}</span>
    </div>
  );
}

/** Charging / discharging at the right of the battery label; on narrow tiles only the symbol stays visible. */
function FlowBadge({ discharging, text }: { discharging: boolean; text: string }) {
  return (
    <span className={`flow ${discharging ? "out" : "in"} ${text.length > 8 ? "long" : ""}`} title={text}>
      <Icon name={discharging ? "arrowDown" : "bolt"} />
      <span className="flow-text">{text}</span>
    </span>
  );
}

export function Overview() {
  const t = useT();
  const tm = useMsg();
  const { reading, control, weather, mode } = useLiveData();
  // Cloud mode has no socket/feed-in split (see app/models.py's normalize_cloud): those fields
  // never arrive at all, so showing "–" tiles for them would look like a fault rather than a
  // difference between data sources - hide the tiles outright instead.
  const cloudMode = mode === "cloud";
  const login = control?.cloud_login;
  const soc = reading?.soc ?? null;
  const bat = reading?.batPow ?? null;
  const levelColor = socColor(soc, Number(control?.settings.NIGHT_MIN_SOC) || undefined);
  const state = control ? (control.enabled ? (control.dry_run ? t("ov.state.dry") : t("ov.state.on")) : t("ov.state.off")) : "";
  // Both timestamps come from the bridge, so this needs no synced clock (unlike Date.now()).
  const meterAgeS = reading?._meterT != null && reading?._t != null ? Math.max(0, reading._t - reading._meterT) : null;
  return (
    <div className="overview-grid">
      <div className="col">
        <EnergyFlow reading={reading} control={control} />
      </div>

      <div className="col">
        {login && !login.ok && (
          <section className="card alert" role="alert">
            <strong>{login.error ? tm(login.error) : ""}</strong>
            {login.retry_in_s ? <p className="hint">{t("ov.loginRetry", { min: Math.ceil(login.retry_in_s / 60) })}</p> : null}
          </section>
        )}
        <section className="card">
          <div className="soc-head">
            <span className="label with-icon" style={{ ["--tile-c" as string]: levelColor }}><BatteryIcon soc={soc} />{t("ov.soc")}</span>
            <strong>{fmt(soc, "%")}</strong>
          </div>
          <div className="bar" role="progressbar" aria-valuenow={soc ?? 0} aria-valuemin={0} aria-valuemax={100}>
            <div style={{ width: `${soc ?? 0}%`, background: levelColor }} />
          </div>
        </section>
        <section className="tiles">
          <Tile icon={<Icon name="sun" />} color="var(--c-pv)" label={t("ov.pv")} value={fmt(reading?.pvPow, "W")}
            hint={reading?.pvPeakTodayW != null ? t("ov.pvPeak", { peak: fmt(reading.pvPeakTodayW, "W") }) : undefined} />
          <Tile icon={<BatteryIcon soc={soc} />} color={levelColor} label={t("ov.battery")} value={fmt(bat === null ? null : Math.abs(bat), "W")}
            badge={bat === null || bat === 0 ? undefined : <FlowBadge discharging={bat > 0} text={bat > 0 ? t("ov.discharging") : t("ov.charging")} />} />
          <Tile icon={<Icon name="inverter" />} color="var(--c-inv)" label={t("ov.inverter")} value={fmt(reading?.invPow, "W")} />
          {!cloudMode && <Tile icon={<Icon name="house" />} color="var(--c-export)" label={t("ov.toGrid")} value={fmt(reading?.exportPow, "W")} />}
          {!cloudMode && <Tile icon={<Icon name="plug" />} color="var(--c-socket)" label={t("ov.socket")} value={fmt(reading?.offGridPow, "W")} />}
          <Tile icon={<Icon name="gauge" />} color="var(--c-grid)" label={t("ov.meter")} value={fmt(reading?.meterPow, "W")}
            hint={meterAgeS != null ? t("ov.meterAge", { s: fmt(meterAgeS, "s") }) : undefined} />
        </section>

        {control && (
          <section className="card">
            <h2 className="with-icon"><Icon name="control" />{t("ov.controller")}</h2>
            <p>{state} · {t("ov.setpoint", { w: fmt(control.setpoint_w, "W") })}</p>
            {control.phase && <p className="hint">{tm(control.phase)}</p>}
            {control.last_action && <p className="hint">{tm(control.last_action)}</p>}
            <p className="hint">
              {t("ov.account", { account: control.account === "main" ? t("account.main") : t("account.guest"), by: control.min_soc_source === "device" ? t("by.device") : t("by.bridge") })}
              {control.device_limits && t("ov.deviceRange", { min: fmt(control.device_limits.soc_min, "%"), max: fmt(control.device_limits.soc_max, "%") })}
            </p>
          </section>
        )}

        {weather?.available && (weather.today || weather.tomorrow) && (
          <section className="card">
            <h2 className="with-icon"><Icon name="cloud" />{t("ov.weather")}</h2>
            <div className="tiles compact">
              {weather.today && <WeatherTile t={t} label={t("ov.weather.today")} day={weather.today} />}
              {weather.tomorrow && <WeatherTile t={t} label={t("ov.weather.tomorrow")} day={weather.tomorrow} />}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
