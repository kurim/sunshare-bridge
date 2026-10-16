import assert from "node:assert/strict";
import { test } from "node:test";
import type { Reading } from "./api.ts";
import { actualSeries, todayYield } from "./lib.ts";

const row = (r: Partial<Reading>): Reading => r as Reading;

test("actualSeries takes the real PV value and falls back to the booked one", () => {
  const rows = [row({ _t: 1, pvPreal: 300, pvPow: 100 }), row({ _t: 2, pvPow: 250 }), row({ _t: 3, pvPreal: 0, pvPow: 80 })];
  assert.deepEqual(actualSeries(rows), [[1, 300], [2, 250], [3, 0]]);
});

test("actualSeries skips rows without a time or a PV value and never goes negative", () => {
  const rows = [row({ pvPow: 5 }), row({ _t: 1 }), row({ _t: 2, pvPow: -4 })];
  assert.deepEqual(actualSeries(rows), [[2, 0]]);
  assert.deepEqual(actualSeries(undefined), []);
});

test("todayYield adds what is reached to what is still expected, so it never reads less than so far", () => {
  assert.equal(todayYield(2.2, 3.2, 0.4).toFixed(1), "3.6");
  assert.equal(todayYield(5, 1, 2), 3);
});

test("todayYield falls back to pvnode's day total without the bridge's own yield", () => {
  assert.equal(todayYield(2.2, null, 0.4), 2.2);
  assert.equal(todayYield(2.2, 3.2, null), 2.2);
});
