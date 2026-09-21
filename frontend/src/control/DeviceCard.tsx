import { useState, type FormEvent } from "react";
import { ApiError, postControl, type ControlStatus } from "../api";
import { fmt } from "../format";
import { useMsg, useT } from "../i18n";

export function DeviceCard({ status, onStatus }: { status: ControlStatus; onStatus: (s: ControlStatus) => void }) {
  const t = useT();
  const tm = useMsg();
  const [watts, setWatts] = useState("");
  const [msg, setMsg] = useState<{ text: string; cls: "ok" | "bad" } | null>(null);
  const [busy, setBusy] = useState(false);
  const main = status.account === "main";
  const limits = status.device_limits;
  const canWrite = status.enabled && !status.dry_run;

  async function setCountryMax(event: FormEvent) {
    event.preventDefault();
    const value = Number(watts);
    if (watts === "" || Number.isNaN(value) || value < 0 || value > 2000) { setMsg({ text: t("dc.range"), cls: "bad" }); return; }
    if (!window.confirm(t("dc.confirm", { w: value }))) return;
    setBusy(true);
    try {
      onStatus(await postControl({ device: { COUNTRY_MAX_POWER: value } }));
      setMsg({ text: t("dc.done", { w: value }), cls: "ok" });
      setWatts("");
    } catch (err) {
      setMsg({ text: err instanceof ApiError && err.msg ? tm(err.msg) : t("dc.failed"), cls: "bad" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <div><h2>{t("dc.title")}</h2><p className="hint">{t("dc.subtitle")}</p></div>
        <span className={`tag ${main ? "ok" : ""}`}>{main ? t("dc.main") : t("dc.guest")}</span>
      </div>

      <p>{t("dc.enforcedBy", { by: status.min_soc_source === "device" ? t("by.device") : t("by.bridge") })}</p>
      {main ? (
        <>
          <div className="tiles compact">
            <div className="tile"><span className="label">{t("dc.socMin")}</span><strong>{fmt(limits?.soc_min, "%")}</strong></div>
            <div className="tile"><span className="label">{t("dc.socMax")}</span><strong>{fmt(limits?.soc_max, "%")}</strong></div>
            <div className="tile"><span className="label">{t("dc.countryMax")}</span><strong>{fmt(limits?.country_max_power, "W")}</strong></div>
          </div>
          {status.device_note && <p className={`hint ${status.device_note.level === "error" ? "bad" : status.device_note.level === "warn" ? "warn" : ""}`}>{tm(status.device_note)}</p>}
          <form className="inline-form" onSubmit={setCountryMax}>
            <label htmlFor="country-max">{t("dc.change")}</label>
            <div className="input-row">
              <input id="country-max" type="number" inputMode="numeric" min={0} max={2000} step={10} value={watts}
                placeholder={limits?.country_max_power != null ? String(limits.country_max_power) : ""}
                onChange={(e) => { setWatts(e.target.value); setMsg(null); }} />
              <span className="unit">W</span>
              <button className="btn primary" type="submit" disabled={busy || !canWrite}>{t("dc.set")}</button>
            </div>
            {!canWrite && <small className="hint">{t("dc.onlyLive")}</small>}
            {msg && <small className={`msg ${msg.cls}`} role="status">{msg.text}</small>}
          </form>
        </>
      ) : (
        <p className="hint">{t("dc.guestInfo")}</p>
      )}
    </section>
  );
}
