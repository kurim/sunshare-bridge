import type { Settings } from "../api";
import { SocBar } from "../components/SocBar";
import { fmt } from "../format";
import { useT } from "../i18n";

const toMin = (hm: string) => { const [h, m] = hm.split(":").map(Number); return h * 60 + m; };
const n = (v: string | number | undefined) => Number(v ?? 0);

export function PlanPreview({ settings: s, soc }: { settings: Settings; soc: number | null }) {
  const t = useT();
  const start = toMin(String(s.NIGHT_START)), end = toMin(String(s.NIGHT_END));
  const now = new Date(), nowMin = now.getHours() * 60 + now.getMinutes();
  const inNight = start === end ? false : start < end ? nowMin >= start && nowMin < end : nowMin >= start || nowMin < end;
  const segments: [number, number][] = start === end ? [] : start < end ? [[start, end]] : [[0, end], [start, 1440]];

  const minSoc = n(s.NIGHT_MIN_SOC), fullSoc = n(s.CHARGE_FULL_SOC);
  const cap = n(s.BATTERY_CAPACITY_WH), reserve = n(s.CHARGE_RESERVE_W), nightMax = n(s.NIGHT_MAX_W);
  const protectionActive = soc != null && soc <= minSoc;
  // Same estimates as the controller (charging assumes 90 % efficiency).
  const fullH = soc != null && soc < fullSoc && reserve > 0 ? (fullSoc - soc) / 100 * cap / 0.9 / reserve : null;
  const nightH = soc != null && soc > minSoc && nightMax > 0 ? (soc - minSoc) / 100 * cap / nightMax : null;

  return (
    <section className="card">
      <div className="card-head">
        <div><h2>{t("pp.title")}</h2><p className="hint">{t("pp.subtitle")}</p></div>
      </div>

      <div className="preview-grid">
        <SocBar soc={soc} settings={s} />

        <div className="plan">
          <span className="label">{t("pp.day")}</span>
          <div className="strip">
            {segments.map(([from, to]) => <div key={from} className="seg" style={{ left: `${from / 14.4}%`, width: `${(to - from) / 14.4}%` }} />)}
            <div className="now" style={{ left: `${nowMin / 14.4}%` }} />
          </div>
          <div className="ticks"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>
          <div className="legend">
            <span><i className="sw day" />{t("pp.legend.day", { w: reserve })}</span>
            <span><i className="sw night" />{t("pp.legend.night", { w: nightMax })}</span>
          </div>
        </div>

        <div className="pills">
          <div>{t("pp.protection")}<b className={protectionActive ? "bad" : ""}>{soc == null ? "–" : protectionActive ? t("pp.protection.active") : t("pp.protection.inactive")}</b></div>
          <div>{t("pp.window")}<b>{inNight ? t("pp.window.night") : t("pp.window.day")} · {String(s.NIGHT_START)}–{String(s.NIGHT_END)}</b></div>
          <div>{t("pp.fullIn")}<b>{fullH != null ? `~${fmt(fullH, "h", 1)}` : soc != null && soc >= fullSoc ? t("pp.full") : "–"}</b></div>
          <div>{t("pp.nightRange")}<b>{nightH != null ? `~${fmt(nightH, "h", 1)}` : "–"}</b></div>
        </div>
      </div>
    </section>
  );
}
