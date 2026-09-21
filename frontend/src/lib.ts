import type { ControlStatus, Reading } from "./api";

const pad2 = (n: number) => String(n).padStart(2, "0");
export const hm = (t: number) => { const d = new Date(t * 1000); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };
export const hms = (t: number) => { const d = new Date(t * 1000); return `${hm(t)}:${pad2(d.getSeconds())}`; };
export const dm = (t: number) => { const d = new Date(t * 1000); return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.`; };
export const dhm = (t: number) => { const d = new Date(t * 1000); return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}. ${hm(t)}`; };

/** Feed-in to the house grid: the inverter's total output minus what its own socket draws (noise <= 3 W ignored). */
export function exportW(r: Reading): number | null {
  if (r.invPow == null || r.offGridPow == null) return null;
  const d = r.invPow - r.offGridPow;
  return d > 3 ? d : 0;
}

/**
 * Colour of a battery level: red at or below the deep-discharge protection (20 % when it is unknown),
 * amber below 50 %, green above, grey without a value.
 */
export function socColor(soc: number | null | undefined, minSoc?: number): string {
  if (soc == null) return "var(--muted)";
  if (soc <= (minSoc ?? 20)) return "var(--bad)";
  return soc < 50 ? "var(--accent)" : "var(--ok)";
}

export type SocketSource = "unknown" | "none" | "unclear" | ("pv" | "bat" | "grid")[];

/** What feeds the inverter output, read off the device fields (verified against captures). */
export function socketSource(r: Reading): SocketSource {
  if (r.offGridPow == null || r.invPow == null) return "unknown";
  if (r.offGridPow < 5 && r.invPow < 5) return "none";
  const src: ("pv" | "bat" | "grid")[] = [];
  if ((r.pvPow ?? 0) > 5) src.push("pv");
  if ((r.batPow ?? 0) > 5) src.push("bat");
  if ((r.gridPow ?? 0) > 5) src.push("grid");
  return src.length ? src : "unclear";
}

// Below this much charged energy the efficiency ratio is too noisy to show.
export const EFF_MIN_KWH = 0.15;

export type Efficiency = { pending: true; charged: number } | { pending: false; pct: number };

/** Battery efficiency since recording began: (discharged + change of stored energy) / charged. */
export function batteryEfficiency(r: Reading | null, control: ControlStatus | null): Efficiency | null {
  const cap = Number(control?.settings.BATTERY_CAPACITY_WH);
  if (!r || !cap || r._effBaseT == null || r.soc == null) return null;
  const charged = (r.batChargeEnergyKwh ?? 0) - (r._effBaseChargeKwh ?? 0);
  const discharged = (r.batDischargeEnergyKwh ?? 0) - (r._effBaseDischargeKwh ?? 0);
  if (charged < EFF_MIN_KWH) return { pending: true, charged };
  const stored = (r.soc - (r._effBaseSoc ?? r.soc)) / 100 * cap / 1000;
  const pct = (discharged + stored) / charged * 100;
  return pct > 0 && pct <= 110 ? { pending: false, pct } : { pending: true, charged };
}

const SMOOTH_KEYS = ["pvPow", "pvPreal", "invPow", "batPow", "batPreal", "offGridPow", "exportPow", "meterPow"] as const;
const SMOOTH_HALF = 3; // centred moving average over ~20 s (7 samples)

/** Live view only; the stored data is untouched (ranges from 6 h up are per-minute averages already). */
export function smooth(rows: Reading[]): Reading[] {
  if (rows.length < 3) return rows;
  return rows.map((row, i) => {
    const out: Reading = { ...row };
    const a = Math.max(0, i - SMOOTH_HALF), b = Math.min(rows.length - 1, i + SMOOTH_HALF);
    for (const k of SMOOTH_KEYS) {
      if (row[k] == null) continue;
      let sum = 0, n = 0;
      for (let j = a; j <= b; j++) { const v = rows[j][k]; if (v != null) { sum += v; n++; } }
      out[k] = sum / n;
    }
    return out;
  });
}
