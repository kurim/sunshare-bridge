import assert from "node:assert/strict";
import { test } from "node:test";
import { allocateFlows, type Flows } from "./flows.ts";

const ZERO: Flows = { pvHome: 0, pvBat: 0, pvGrid: 0, batHome: 0, batGrid: 0, gridHome: 0, gridBat: 0 };
const flows = (part: Partial<Flows>): Flows => ({ ...ZERO, ...part });

// ---- with the inverter output (the normal case) ----

test("solar charges the battery first, the inverter output serves the house", () => {
  assert.deepEqual(allocateFlows({ pv: 467, bat: -309, meter: 0, home: 158, inv: 158 }), flows({ pvHome: 158, pvBat: 309 }));
});

test("inverter at 0 W: solar goes into the battery and the grid alone supplies the house", () => {
  // the case seen on a real device: PV 65 W, battery charging 65 W, house 372 W from the grid
  assert.deepEqual(allocateFlows({ pv: 65, bat: -65, meter: 372, home: 372, inv: 0 }), flows({ pvBat: 65, gridHome: 372 }));
});

test("at night the battery and the grid share the house load", () => {
  assert.deepEqual(allocateFlows({ pv: 0, bat: 150, meter: 300, home: 450, inv: 150 }), flows({ batHome: 150, gridHome: 300 }));
});

test("surplus solar is fed into the grid", () => {
  assert.deepEqual(allocateFlows({ pv: 700, bat: 0, meter: -300, home: 220, inv: 520 }), flows({ pvHome: 220, pvGrid: 300 }));
});

test("the grid charges the battery next to serving the house", () => {
  assert.deepEqual(allocateFlows({ pv: 0, bat: -200, meter: 350, home: 150, inv: 0 }), flows({ gridHome: 150, gridBat: 200 }));
});

test("solar and the grid together charge the battery", () => {
  assert.deepEqual(allocateFlows({ pv: 100, bat: -300, meter: 300, home: 0, inv: 0 }), flows({ pvBat: 100, gridBat: 200 }));
});

test("the battery feeds the grid after the house is served", () => {
  assert.deepEqual(allocateFlows({ pv: 0, bat: 400, meter: -100, home: 300, inv: 400 }), flows({ batHome: 300, batGrid: 100 }));
});

test("solar, battery and grid supply one house", () => {
  assert.deepEqual(allocateFlows({ pv: 100, bat: 100, meter: 100, home: 300, inv: 200 }), flows({ pvHome: 100, batHome: 100, gridHome: 100 }));
});

test("idle system: no flow at all", () => {
  assert.deepEqual(allocateFlows({ pv: 0, bat: 0, meter: 0, home: 0, inv: 0 }), ZERO);
});

// ---- without the inverter output: priority house, battery, grid ----

test("without inverter output the sources serve house, battery and grid in that order", () => {
  assert.deepEqual(allocateFlows({ pv: 467, bat: -309, meter: 0, home: 158, inv: null }), flows({ pvHome: 158, pvBat: 309 }));
  assert.deepEqual(allocateFlows({ pv: 700, bat: 0, meter: -300, home: 220, inv: null }), flows({ pvHome: 220, pvGrid: 300 }));
  assert.deepEqual(allocateFlows({ pv: 300, bat: -100, meter: null, home: 200, inv: null }), flows({ pvHome: 200, pvBat: 100 }));
});

// ---- invariants ----

test("nothing is ever negative and no node gives or takes more than it has", () => {
  const values = [-50, 0, 5, 80, 300, 900];
  for (const pv of values) for (const bat of values) for (const m of [...values, null]) for (const home of values) for (const inv of [...values, null]) {
    const c = { pv, bat, meter: m, home, inv };
    const f = allocateFlows(c);
    const tag = JSON.stringify([c, f]);
    for (const v of Object.values(f)) assert.ok(v >= 0, tag);
    assert.ok(f.pvHome + f.pvBat + f.pvGrid <= Math.max(0, pv) + 1e-9, tag);
    assert.ok(f.batHome + f.batGrid <= Math.max(0, bat) + 1e-9, tag);
    assert.ok(f.gridHome + f.gridBat <= Math.max(0, m ?? 0) + 1e-9, tag);
    assert.ok(f.pvHome + f.batHome + f.gridHome <= Math.max(0, home) + 1e-9, tag);
    assert.ok(f.pvBat + f.gridBat <= Math.max(0, -bat) + 1e-9, tag);
    assert.ok(f.pvGrid + f.batGrid <= Math.max(0, -(m ?? 0)) + 1e-9, tag);
    if (inv != null) assert.ok(f.pvHome + f.pvGrid + f.batHome + f.batGrid <= Math.max(0, inv) + 1e-9, tag);
  }
});
