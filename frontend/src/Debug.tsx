import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clearDebug, getDebug, Unauthorized, type DebugEntry } from "./api";
import { useMsg, useT, type Key } from "./i18n";

const POLL_MS = 2000;
const MAX_KEPT = 3000;
const MAX_DOM = 300;
const KINDS = ["meter", "step", "write", "guard", "failsafe", "sync", "phase", "config"] as const;
// Order of the numbers shown under an entry; SOC is a percentage, everything else watts.
const CTX_ORDER = ["meter", "pv", "pvMin", "inv", "bat", "soc", "cap", "error", "setpoint", "w", "reserve"] as const;

const clock = (t: number) => new Date(t * 1000).toLocaleTimeString(undefined, { hour12: false });

/** The controller's debug trail, polled: entries newer than the last one seen are appended. A restart or
 * a clear on the server shows up as a lower `last_id` - the view then starts over. */
function useDebugLog(onSessionEnded: () => void) {
  const [entries, setEntries] = useState<DebugEntry[]>([]);
  const [size, setSize] = useState(0);
  const [up, setUp] = useState(false);
  const [paused, setPaused] = useState(false);
  const lastId = useRef(0);

  const poll = useCallback(async () => {
    try {
      let snap = await getDebug(lastId.current);
      if (snap.last_id < lastId.current) { // bridge restarted: the counter began again
        lastId.current = 0;
        snap = await getDebug(0);
        setEntries([]);
      }
      setUp(true);
      setSize(snap.size);
      if (snap.entries.length) {
        lastId.current = snap.entries[snap.entries.length - 1].id;
        setEntries((old) => [...old, ...snap.entries].slice(-MAX_KEPT));
      }
    } catch (err) {
      if (err instanceof Unauthorized) onSessionEnded();
      else setUp(false);
    }
  }, [onSessionEnded]);

  useEffect(() => {
    if (paused) return;
    void poll();
    const timer = setInterval(() => { void poll(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [paused, poll]);

  const clear = useCallback(async () => {
    try { await clearDebug(); } catch { /* the view is emptied either way */ }
    setEntries([]);
  }, []);

  return { entries, size, up, paused, setPaused, clear };
}

const levelTag = (level: string) => (level === "error" ? "bad" : level === "warn" ? "warn" : level === "ok" ? "ok" : "");

export function Debug({ onSessionEnded }: { onSessionEnded: () => void }) {
  const t = useT();
  const tm = useMsg();
  const { entries, size, up, paused, setPaused, clear } = useDebugLog(onSessionEnded);
  const [kind, setKind] = useState("");
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();

  const visible = useMemo(() => {
    const rows = entries.filter((e) => (!kind || e.kind === kind) && (!needle || tm(e.msg).toLowerCase().includes(needle)));
    return rows.slice(-MAX_DOM).reverse();
  }, [entries, kind, needle, tm]);

  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(entries, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `sunshare-debug-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h2>{t("dbg.title")}</h2>
          <p className="hint">{t("dbg.subtitle")}</p>
        </div>
        <span className={`tag ${paused ? "warn" : up ? "ok" : "bad"}`}>{paused ? t("dbg.state.paused") : up ? t("dbg.state.live") : t("dbg.state.offline")}</span>
      </div>
      <div className="rawbar">
        <button className="btn" type="button" onClick={() => setPaused(!paused)}>{paused ? t("dbg.resume") : t("dbg.pause")}</button>
        <button className="btn" type="button" onClick={() => { void clear(); }}>{t("dbg.clear")}</button>
        <button className="btn" type="button" onClick={download} disabled={!entries.length}>{t("dbg.download")}</button>
        <select value={kind} aria-label={t("dbg.kind.all")} onChange={(e) => setKind(e.target.value)}>
          <option value="">{t("dbg.kind.all")}</option>
          {KINDS.map((k) => <option key={k} value={k}>{t(`dbg.kind.${k}` as Key)}</option>)}
        </select>
        <input type="search" placeholder={t("dbg.filter")} aria-label={t("dbg.filter")} value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <p className="hint">{t("dbg.count", { n: entries.length, size })}</p>
      <p className="hint">{t("dbg.legend")}</p>
      <div className="dbg-list">
        {entries.length === 0 && <p className="hint">{t("dbg.empty")}</p>}
        {entries.length > 0 && visible.length === 0 && <p className="hint">{t("dbg.noMatch")}</p>}
        {visible.map((e) => (
          <div className="dbg-row" key={e.id}>
            <div className="dbg-main">
              <span className="dbg-time">{clock(e.t)}</span>
              <span className={`tag ${levelTag(e.msg.level)}`}>{t(`dbg.kind.${e.kind}` as Key)}</span>
              <span className="dbg-text">{tm(e.msg)}</span>
            </div>
            <div className="dbg-ctx">
              {CTX_ORDER.filter((k) => e.ctx[k] != null).map((k) => (
                <span key={k}>{t(`dbg.c.${k}` as Key)} <b>{e.ctx[k]}{k === "soc" ? " %" : " W"}</b></span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
