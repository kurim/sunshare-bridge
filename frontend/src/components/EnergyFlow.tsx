import type { CSSProperties } from "react";
import type { ControlStatus, Reading } from "../api";
import { fmt } from "../format";
import { useT } from "../i18n";
import { useMotion } from "../motion";
import { allocateFlows } from "../flows";
import { socColor } from "../lib";
import { BatteryIcon, Icon } from "./Icons";

const ACTIVE_W = 5; // below this a line counts as idle (sensor noise)

// The diagram is drawn on a 400 x 430 board; nodes are positioned in percent of it, lines in board units.
// No top margin (the solar node sits flush at y=0) so it lines up with the card next to it; a 10-unit
// margin is kept on the other three sides.
const NODE = {
  solar: { x: 10, y: 0, w: 380, h: 90 },
  grid: { x: 10, y: 130, w: 140, h: 160 },
  battery: { x: 250, y: 130, w: 140, h: 160 },
  home: { x: 10, y: 330, w: 380, h: 90 },
};
const pos = (n: { x: number; y: number; w: number; h: number }): CSSProperties => ({
  left: `${n.x / 4}%`, top: `${n.y / 4.3}%`, width: `${n.w / 4}%`, height: `${n.h / 4.3}%`,
});

// Every pair of nodes has its own pipe, so each node has three connections (one to each of the others) and
// you see where the energy comes from and where it goes. Each pipe is drawn from the first to the second
// node; the pulses run that way ("forward") or, for `reverse`, the other way.
const LANE = {
  pvHome: "M200 90 V330",
  pvBat: "M214 90 V155 Q214 175 234 175 H250",
  pvGrid: "M186 90 V155 Q186 175 166 175 H150",
  batHome: "M250 245 H234 Q214 245 214 265 V330",
  gridHome: "M150 245 H166 Q186 245 186 265 V330",
  batGrid: "M250 210 H150", // forward = battery feeds the grid, reverse = the grid charges the battery
} as const;

interface Lane { d: string; watts: number; color: string; reverse?: boolean }

/**
 * A lit pipe: a coloured core and bright pulses travelling along it. Pulse speed and thickness follow the
 * power: 0 W = calm, 800 W and more = fast and thick.
 */
function Lit({ d, watts, color, reverse = false }: Lane) {
  const p = Math.min(Math.abs(watts), 800) / 800;
  const style = { ["--lc" as string]: color, ["--dur" as string]: `${(1.7 - 1.2 * p).toFixed(2)}s` } as CSSProperties;
  return (
    <g style={style}>
      <path d={d} className="ef-core" />
      <path d={d} className={`ef-pulse ${reverse ? "rev" : ""}`} style={{ strokeWidth: 3.5 + 2.5 * p }} />
    </g>
  );
}

export function EnergyFlow({ reading, control }: { reading: Reading | null; control: ControlStatus | null }) {
  const t = useT();
  const { pref, setPref, active, systemReduced } = useMotion();
  const pv = Math.max(0, reading?.pvPow ?? 0);
  const bat = reading?.batPow ?? 0; // + discharging, - charging
  const soc = reading?.soc ?? null;
  const inv = reading?.invPow ?? null;
  const meter = reading?.meterPow ?? control?.meter_w ?? null; // + import, - feed-in
  // Household consumption needs the grid meter; without it only the inverter output is known.
  const home = meter != null && inv != null ? Math.max(0, meter + inv) : inv;
  const today = reading?.pvEnergyTodayKwh ?? reading?.todayEnergyKwh ?? null;
  const level = socColor(soc, Number(control?.settings.NIGHT_MIN_SOC) || undefined);
  const charging = bat < -ACTIVE_W, discharging = bat > ACTIVE_W;
  const f = allocateFlows({ pv, bat, meter, home: home ?? 0, inv });
  const gridToBat = f.batGrid < ACTIVE_W && f.gridBat >= ACTIVE_W;
  const lanes: Lane[] = [
    { d: LANE.pvHome, watts: f.pvHome, color: "var(--c-pv)" },
    { d: LANE.pvBat, watts: f.pvBat, color: "var(--c-pv)" },
    { d: LANE.pvGrid, watts: f.pvGrid, color: "var(--c-pv)" },
    { d: LANE.batHome, watts: f.batHome, color: "var(--c-bat)" },
    { d: LANE.gridHome, watts: f.gridHome, color: "var(--c-grid)" },
    gridToBat
      ? { d: LANE.batGrid, watts: f.gridBat, color: "var(--c-grid)", reverse: true }
      : { d: LANE.batGrid, watts: f.batGrid, color: "var(--c-bat)" },
  ];

  return (
    <div>
    <div className="energy-flow" role="img"
      aria-label={t("fd.aria", { pv: fmt(pv, "W"), grid: fmt(meter, "W"), bat: fmt(Math.abs(bat), "W"), soc: fmt(soc, "%"), home: fmt(home, "W") })}>
      <svg viewBox="0 0 400 430" aria-hidden="true">
        {lanes.map((l) => <path key={l.d} d={l.d} className="ef-track" />)}
        {lanes.filter((l) => l.watts >= ACTIVE_W).map((l) => <Lit key={l.d} {...l} />)}
      </svg>

      <div className="ef-node ef-solar" style={{ ...pos(NODE.solar), ["--node-c" as string]: "var(--c-pv)" }}>
        <div className="ef-head">
          <span className="ef-title"><Icon name="sun" />{t("fd.solar")}</span>
          {today != null && <span className="ef-side">{t("fd.today", { kwh: fmt(today, "", 2, true) })}</span>}
        </div>
        <span className="ef-value">{fmt(reading?.pvPow, "W")}</span>
      </div>

      <div className="ef-node ef-grid" style={{ ...pos(NODE.grid), ["--node-c" as string]: "var(--c-grid)" }}>
        <div className="ef-head"><span className="ef-title"><Icon name="grid" />{t("fd.grid")}</span></div>
        <div>
          <span className="ef-value">{fmt(meter == null ? null : Math.abs(meter), "W")}</span>
          {meter != null && Math.abs(meter) >= ACTIVE_W && <span className="ef-state">{meter > 0 ? t("fd.import") : t("fd.export")}</span>}
        </div>
      </div>

      <div className="ef-node ef-battery" style={{ ...pos(NODE.battery), ["--node-c" as string]: level }}>
        <div className="ef-fill" style={{ height: `${Math.max(0, Math.min(100, soc ?? 0))}%` }} />
        <div className="ef-head">
          <span className="ef-title"><BatteryIcon soc={soc} />{t("fd.battery")}</span>
          <span className="ef-soc">{fmt(soc, "%")}</span>
        </div>
        <div>
          <span className="ef-value">{fmt(Math.abs(bat), "W")}</span>
          {(charging || discharging) && (
            <span className={`ef-state ${charging ? "in" : "out"}`}>
              <Icon name={charging ? "bolt" : "arrowDown"} />{charging ? t("fd.charging") : t("fd.discharging")}
            </span>
          )}
        </div>
      </div>

      <div className="ef-node ef-home" style={{ ...pos(NODE.home), ["--node-c" as string]: "var(--c-inv)" }}>
        <div className="ef-head">
          <span className="ef-title"><Icon name="house" />{t("fd.home")}</span>
          {meter == null && <span className="ef-side">{t("fd.homeNoMeter")}</span>}
        </div>
        <span className="ef-value">{fmt(home, "W")}</span>
      </div>
    </div>
    <div className="ef-foot">
      {pref === "auto" && systemReduced && <span className="hint">{t("fd.motion.hint")}</span>}
      <button type="button" className="link with-icon" aria-pressed={active} onClick={() => setPref(active ? "off" : "on")}>
        <Icon name={active ? "pause" : "play"} />{active ? t("fd.motion.off") : t("fd.motion.on")}
      </button>
    </div>
    </div>
  );
}
