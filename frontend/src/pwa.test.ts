import assert from "node:assert/strict";
import { test } from "node:test";
import { HIDDEN_IN_PWA, isStandalone, type PwaEnv } from "./pwa.ts";

const win = (standalone: boolean | undefined, matches: boolean) =>
  ({ navigator: { standalone }, matchMedia: () => ({ matches }) }) as unknown as PwaEnv;

test("isStandalone: iOS flag or the standalone display mode", () => {
  assert.equal(isStandalone(win(true, false)), true);
  assert.equal(isStandalone(win(undefined, true)), true);
  assert.equal(isStandalone(win(undefined, false)), false);
  assert.equal(isStandalone(win(false, false)), false);
});

test("the raw log and the debug log are the pages hidden in the app", () => {
  assert.deepEqual([...HIDDEN_IN_PWA], ["/raw", "/debug"]);
});
