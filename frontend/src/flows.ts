/** Power in watts flowing from one node to another. */
export interface Flows {
  pvHome: number;
  pvBat: number;
  pvGrid: number;
  batHome: number;
  batGrid: number;
  gridHome: number;
  gridBat: number;
}

export interface FlowInput {
  /** Solar generation (>= 0). */
  pv: number;
  /** Battery power: + discharging, - charging. */
  bat: number;
  /** Grid meter: + import, - feed-in; null = no meter. */
  meter: number | null;
  /** Household consumption. */
  home: number;
  /** Total output of the inverter (goes to the house and the grid); null = unknown. */
  inv: number | null;
}

const pos = (v: number) => Math.max(0, v);

/**
 * Splits the measured totals into the flows between the four nodes. The device only measures totals,
 * so this is an allocation, not a measurement.
 *
 * With the inverter output known (the normal case) it follows the device: solar first charges the
 * battery, whatever solar and battery discharge then deliver is exactly the inverter output, which
 * serves the house first and feeds the grid with the rest; the grid covers what the house still lacks
 * and, if the battery charges more than solar provides, the difference.
 * Without it, every source falls back to the usual priority: house, battery, grid.
 * Leftovers nobody asked for (noise, losses) are dropped.
 */
export function allocateFlows({ pv, bat, meter, home, inv }: FlowInput): Flows {
  const sPv = pos(pv), batDis = pos(bat), batChg = pos(-bat);
  const imp = pos(meter ?? 0), exp = pos(-(meter ?? 0));
  const dHome = pos(home);

  if (inv == null) return byPriority(sPv, batDis, batChg, imp, exp, dHome);

  const out = pos(inv);
  const pvBat = Math.min(sPv, batChg);                      // solar charges the battery first
  const pvOut = Math.min(sPv - pvBat, out);
  const batOut = Math.min(batDis, out - pvOut);
  const outHome = Math.min(pos(out - exp), dHome);           // what the house asks for, the rest of the output leaves as feed-in
  const pvHome = Math.min(pvOut, outHome);
  const batHome = Math.min(batOut, outHome - pvHome);
  const pvGrid = Math.min(pvOut - pvHome, exp);              // ... but never more than the meter sees leaving
  const batGrid = Math.min(batOut - batHome, exp - pvGrid);
  const gridHome = Math.min(imp, pos(dHome - pvHome - batHome));
  const gridBat = Math.min(imp - gridHome, batChg - pvBat);  // the rest of the charging comes from the grid
  return { pvHome, pvBat, pvGrid, batHome, batGrid, gridHome, gridBat };
}

function byPriority(sPv: number, sBat: number, batChg: number, sGrid: number, exp: number, home: number): Flows {
  let dHome = home, dBat = batChg, dGrid = exp;
  const pvHome = Math.min(sPv, dHome); dHome -= pvHome;
  const pvBat = Math.min(sPv - pvHome, dBat); dBat -= pvBat;
  const pvGrid = Math.min(sPv - pvHome - pvBat, dGrid); dGrid -= pvGrid;
  const batHome = Math.min(sBat, dHome); dHome -= batHome;
  const batGrid = Math.min(sBat - batHome, dGrid);
  const gridHome = Math.min(sGrid, dHome);
  const gridBat = Math.min(sGrid - gridHome, dBat);
  return { pvHome, pvBat, pvGrid, batHome, batGrid, gridHome, gridBat };
}
