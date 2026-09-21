import type { ControlStatus } from "../api";
import { fmt } from "../format";
import { useT } from "../i18n";

/** Battery bar with the plan's thresholds marked (protection, release, full). */
export function SocBar({ soc, settings }: { soc: number | null; settings: ControlStatus["settings"] | undefined }) {
  const t = useT();
  const cap = Number(settings?.BATTERY_CAPACITY_WH) || 0;
  const marks = settings
    ? [
        { v: Number(settings.NIGHT_MIN_SOC), label: t("soc.protect"), cls: "bad" },
        { v: Number(settings.CHARGE_RELEASE_SOC), label: t("soc.release"), cls: "" },
        { v: Number(settings.CHARGE_FULL_SOC), label: t("soc.full"), cls: "ok" },
      ]
    : [];
  return (
    <div className="soc-preview">
      <div className="soc-head">
        <span className="label">{t("soc.title")}</span>
        <strong>{fmt(soc, "%")}</strong>
      </div>
      {cap > 0 && soc != null && <p className="hint">{t("soc.of", { a: fmt(soc / 100 * cap, "Wh"), b: fmt(cap, "Wh") })}</p>}
      <div className="track" role="img" aria-label={t("soc.aria", { v: soc ?? t("soc.unknown") })}>
        <div className="fill" style={{ width: `${Math.min(soc ?? 0, 100)}%` }} />
        {marks.map((m) => <i key={m.label} className={`mark ${m.cls}`} style={{ left: `${m.v}%` }} title={`${m.label} ${m.v} %`} />)}
      </div>
      {marks.length > 0 && (
        <div className="legend">
          {marks.map((m) => <span key={m.label}><i className={`sw ${m.cls}`} />{m.label} {m.v} %</span>)}
        </div>
      )}
    </div>
  );
}
