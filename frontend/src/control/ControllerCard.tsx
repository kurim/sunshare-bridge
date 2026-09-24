import { useState } from "react";
import { ApiError, postControl, type ControlStatus, type ControlUpdate } from "../api";
import { fmt } from "../format";
import { useMsg, useT } from "../i18n";

function Toggle({ label, hint, checked, tag, tagClass, disabled, onChange }: {
  label: string; hint: string; checked: boolean; tag: string; tagClass: string; disabled: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-text"><b>{label}</b><small>{hint}</small></span>
      <span className={`tag ${tagClass}`}>{tag}</span>
    </label>
  );
}

function pretty(text: string): string {
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; }
}

export function ControllerCard({ status, onStatus }: { status: ControlStatus; onStatus: (s: ControlStatus) => void }) {
  const t = useT();
  const tm = useMsg();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function change(update: ControlUpdate) {
    const next = { enabled: status.enabled, dry_run: status.dry_run, ...update };
    const wasLive = status.enabled && !status.dry_run;
    const willBeLive = next.enabled && !next.dry_run;
    if (willBeLive && !wasLive && !window.confirm(t("cc.confirmLive"))) return;
    setBusy(true);
    setError("");
    try {
      onStatus(await postControl(update));
    } catch (err) {
      setError(err instanceof ApiError && err.msg ? tm(err.msg) : t("cc.changeFailed"));
    } finally {
      setBusy(false);
    }
  }

  const live = status.enabled && !status.dry_run;
  const meter = status.meter_w;
  const login = status.cloud_login && !status.cloud_login.ok ? status.cloud_login : null;
  const lastAction = login
    ? `${login.error ? tm(login.error) : ""}${login.retry_in_s ? t("cc.retryIn", { min: Math.ceil(login.retry_in_s / 60) }) : ""}`
    : status.last_action ? tm(status.last_action) : "–";
  const level = login ? "error" : status.last_action?.level;
  const bad = level === "error";
  const warn = level === "warn";
  const estimates = [
    status.est_full_h != null ? t("cc.est.full", { h: fmt(status.est_full_h, "h", 1) }) : null,
    status.est_night_h != null ? t("cc.est.night", { h: fmt(status.est_night_h, "h", 1) }) : null,
  ].filter(Boolean).join(" · ");
  const diagOpen = status.meter_w == null || !status.mqtt_connected;

  return (
    <section className="card">
      <div className="card-head">
        <div><h2>{t("cc.title")}</h2><p className="hint">{t("cc.subtitle")}</p></div>
        <span className={`tag ${!status.enabled ? "" : status.dry_run ? "warn" : "ok"}`}>
          {!status.enabled ? t("cc.tag.off") : status.dry_run ? t("cc.tag.dry") : t("cc.tag.on")}
        </span>
      </div>

      <div className="tiles compact">
        <div className="tile">
          <span className="label">{t("cc.meter")}</span>
          <strong>{fmt(meter, "W")}</strong>
          <span className={`hint ${meter == null ? "" : meter > 0 ? "bad" : meter < 0 ? "warn" : "ok"}`}>
            {meter == null ? t("cc.meter.none") : meter > 0 ? t("cc.meter.import") : meter < 0 ? t("cc.meter.export") : t("cc.meter.balanced")}
          </span>
        </div>
        <div className="tile">
          <span className="label">{t("cc.inverter")}</span>
          <strong>{fmt(status.inverter_w, "W")}</strong>
          <span className="hint">
            {status.inverter_w != null && status.control_max_w ? t("cc.inverter.load", { pct: fmt(status.inverter_w / status.control_max_w * 100, "%") }) : "–"}
          </span>
        </div>
        <div className="tile">
          <span className="label">{t("cc.setpoint")}</span>
          <strong>{fmt(status.setpoint_w, "W")}</strong>
          <span className="hint">
            {status.setpoint_w != null && status.inverter_w != null
              ? t("cc.setpoint.delta", { w: fmt(status.inverter_w - status.setpoint_w, "W") }) : t("cc.setpoint.target", { w: fmt(status.target_w, "W") })}
          </span>
        </div>
      </div>

      <div className="toggles">
        <Toggle label={t("cc.enabled")} hint={t("cc.enabled.hint")} checked={status.enabled} disabled={busy}
          tag={live ? t("cc.badge.running") : status.enabled ? t("cc.badge.simulation") : t("cc.badge.off")} tagClass={live ? "ok" : status.enabled ? "warn" : ""}
          onChange={(v) => change({ enabled: v })} />
        <Toggle label={t("cc.dry")} hint={t("cc.dry.hint")} checked={status.dry_run} disabled={busy}
          tag={status.dry_run ? t("cc.badge.on") : t("cc.badge.off")} tagClass={status.dry_run ? "warn" : ""}
          onChange={(v) => change({ dry_run: v })} />
        <Toggle label={t("cc.plan")} hint={t("cc.plan.hint")} checked={status.plan} disabled={busy}
          tag={status.plan ? t("cc.badge.auto") : t("cc.badge.off")} tagClass={status.plan ? "info" : ""}
          onChange={(v) => change({ plan: v })} />
        <Toggle label={t("cc.coverLoad")} hint={t("cc.coverLoad.hint")} checked={status.cover_load} disabled={busy}
          tag={status.cover_load ? t("cc.badge.on") : t("cc.badge.off")} tagClass={status.cover_load ? "info" : ""}
          onChange={(v) => change({ cover_load: v })} />
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      {(status.phase || estimates) && (
        <div className="note">
          {status.phase && <b>{tm(status.phase)}</b>}
          {estimates && <small>{estimates}</small>}
        </div>
      )}
      <p className={`status-line ${bad ? "bad" : warn ? "warn" : ""}`}><span className="dot-inline" />{lastAction}</p>

      <details open={diagOpen}>
        <summary>{t("cc.diag")}</summary>
        <pre>
          {`${t("cc.diag.mqtt", { state: status.mqtt_connected ? t("cc.diag.connected") : t("cc.diag.disconnected"), discovery: status.config_seen ? t("cc.diag.found") : t("cc.diag.missing") })}\n` +
            `${t("cc.diag.topic", { topic: status.state_topic ?? "–", path: status.value_path ?? t("cc.diag.plain") })}\n` +
            `${t("cc.diag.last")} ${status.last_payload ? `\n${pretty(status.last_payload)}` : t("cc.diag.none")}`}
        </pre>
      </details>
    </section>
  );
}
