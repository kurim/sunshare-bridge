import { useMemo, useState } from "react";
import { clearRaw } from "./api";
import { fmt } from "./format";
import { useT } from "./i18n";
import { Entry } from "./raw/Entry";
import { useRawLog } from "./raw/useRawLog";

// Fields the bridge evaluates; everything else is shown as "ungenutzt".
const USED = new Set(["time", "pvPow", "pv1Pow", "pv2Pow", "invPow", "batPow", "loadPow", "gridPow", "offGridPow", "otherPow", "soc", "bhs"]);
const MAX_DOM = 200;

export function Raw({ onSessionEnded }: { onSessionEnded: () => void }) {
  const t = useT();
  const { entries, fields, size, up, paused, setPaused } = useRawLog(onSessionEnded);
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();

  const visible = useMemo(
    () => entries.filter((e) => !needle || e.body.toLowerCase().includes(needle)).slice(-MAX_DOM).reverse(),
    // `entries` is mutated in place, so the length and the newest id stand in for its identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [needle, entries.length, entries[entries.length - 1]?.id, entries[0]?.id],
  );

  let avg: number | null = null;
  if (entries.length > 2) {
    const last = entries.slice(-21);
    avg = (last[last.length - 1].t - last[0].t) / (last.length - 1);
  }

  const download = () => {
    const data = entries.map(({ obj: _obj, ...e }) => e);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `sunshare-raw-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <>
      <section className="card">
        <div className="card-head">
          <div>
            <h2>{t("rw.title")}</h2>
            <p className="hint">{t("rw.subtitle", { path: "/collect-service/collect/emsRealDataMinute/realTimeElectricFlow" })}</p>
          </div>
          <span className={`tag ${paused ? "warn" : up ? "ok" : "bad"}`}>{paused ? t("rw.state.paused") : up ? t("rw.state.live") : t("rw.state.offline")}</span>
        </div>
        <div className="rawbar">
          <button className="btn" type="button" onClick={() => setPaused(!paused)}>{paused ? t("rw.resume") : t("rw.pause")}</button>
          <button className="btn" type="button" onClick={() => { void clearRaw(); }}>{t("rw.clear")}</button>
          <button className="btn" type="button" onClick={download} disabled={!entries.length}>{t("rw.download")}</button>
          <input type="search" placeholder={t("rw.filter")} aria-label={t("rw.filter")} value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <p className="hint">
          {t("rw.count", { n: entries.length, size })}{avg != null ? t("rw.avgGap", { s: fmt(avg, "s", 1) }) : ""}
        </p>
      </section>

      <div className="raw-cols">
        <section className="card">
          <div className="card-head"><h2>{t("rw.fields")}</h2><span className="tag">{fields.length ? t("rw.fieldsCount", { n: fields.length }) : "–"}</span></div>
          <p className="hint">{t("rw.fieldsHelp")}</p>
          <div className="pane">
            {fields.length === 0 && <p className="hint">{t("rw.waiting")}</p>}
            {fields.map((f) => (
              <div key={f.key} className="frow">
                <span className="fk">{USED.has(f.key) ? <span className="ok" title={t("rw.used")}>● </span> : <span className="tag">{t("rw.unused")}</span>}{f.key}</span>
                {/* new key on every change restarts the flash animation */}
                <span key={f.changes} className={`fv ${f.changes ? "flash" : ""}`}>{f.value}</span>
                <span className="fc" title={t("rw.changes")}>{f.changes}×</span>
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <div className="card-head"><h2>{t("rw.log")}</h2><span className="tag">{needle ? `${visible.length} / ${entries.length}` : entries.length}</span></div>
          <p className="hint">{t("rw.logHelp")}</p>
          <div className="pane">
            {visible.length === 0 && <p className="hint">{entries.length ? t("rw.noMatch") : t("rw.waiting")}</p>}
            {visible.map((e) => <Entry key={e.id} entry={e} respStatus={e.resp_status} respBody={e.resp_body} />)}
          </div>
        </section>
      </div>
    </>
  );
}
