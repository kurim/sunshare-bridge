import { useEffect, useState } from "react";
import { ApiError, postControl, type ControlStatus, type Settings } from "../api";
import { useMsg, useT, type Key } from "../i18n";
import { FIELDS, effective, toForm, toPayload, validate, type Form } from "./fields";

export function SettingsCard({ status, onStatus, onPreview }: {
  status: ControlStatus;
  onStatus: (s: ControlStatus) => void;
  onPreview: (values: Settings) => void;
}) {
  const t = useT();
  const tm = useMsg();
  const [form, setForm] = useState<Form>(() => toForm(status.settings));
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<{ text: string; cls: "ok" | "warn" | "bad" } | null>(null);
  const [invalid, setInvalid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Follow the bridge's values as long as nothing is being edited.
  useEffect(() => { if (!dirty) setForm(toForm(status.settings)); }, [status.settings, dirty]);
  useEffect(() => { onPreview(effective(status.settings, form, dirty)); }, [status.settings, form, dirty, onPreview]);

  const edit = (key: string, value: string) => {
    setForm((f) => ({ ...f, [key]: value }));
    setDirty(true);
    setInvalid(null);
    setMsg(null);
  };

  async function save() {
    const problem = validate(form, t);
    if (problem) { setInvalid(problem.key); setMsg({ text: problem.text, cls: "bad" }); return; }
    setBusy(true);
    try {
      const next = await postControl({ settings: toPayload(form) });
      onStatus(next);
      setForm(toForm(next.settings));
      setDirty(false);
      setMsg({ text: t("sc.saved"), cls: "ok" });
    } catch (err) {
      // the bridge's validation errors arrive as translatable messages
      setMsg({ text: err instanceof ApiError && err.msg ? tm(err.msg) : t("sc.saveFailed"), cls: "bad" });
    } finally {
      setBusy(false);
    }
  }

  const helpKey = (key: string): Key =>
    (key === "NIGHT_MIN_SOC" && status.account === "main" ? "field.NIGHT_MIN_SOC.helpMain" : `field.${key}.help`) as Key;

  return (
    <section className="card">
      <div className="card-head">
        <div><h2>{t("sc.title")}</h2><p className="hint">{t("sc.subtitle")}</p></div>
        {dirty && <span className="tag warn">{t("sc.dirty")}</span>}
      </div>

      <form className="fields" onSubmit={(e) => { e.preventDefault(); void save(); }} noValidate>
        {FIELDS.map((f) => (
          <div key={f.key} className="field">
            <label htmlFor={`f-${f.key}`}>
              <span>{t(`field.${f.key}` as Key)}</span>
              <code>{f.key}</code>
            </label>
            <div className="input-row">
              <input
                id={`f-${f.key}`}
                type={f.kind === "time" ? "time" : f.kind === "range" ? "range" : "number"}
                inputMode={f.kind === "number" ? "numeric" : undefined}
                min={f.min} max={f.max} step={f.step}
                value={form[f.key]}
                aria-invalid={invalid === f.key}
                onChange={(e) => edit(f.key, e.target.value)}
              />
              {f.kind === "range" && <span className="range-value">{form[f.key]} %</span>}
              {f.kind === "number" && <span className="unit">{f.unit}</span>}
            </div>
            <small className="hint">{t(helpKey(f.key))}</small>
          </div>
        ))}

        <div className="actions">
          <span className={`msg ${msg?.cls ?? ""}`} role="status">{msg?.text}</span>
          <button type="button" className="btn" onClick={() => { setForm(toForm(status.defaults)); setDirty(true); setMsg({ text: t("sc.defaultsLoaded"), cls: "warn" }); }}>
            {t("sc.defaults")}
          </button>
          <button type="button" className="btn" disabled={!dirty} onClick={() => { setDirty(false); setForm(toForm(status.settings)); setMsg(null); setInvalid(null); }}>
            {t("sc.revert")}
          </button>
          <button type="submit" className="btn primary" disabled={!dirty || busy}>{t("sc.save")}</button>
        </div>
      </form>
    </section>
  );
}
