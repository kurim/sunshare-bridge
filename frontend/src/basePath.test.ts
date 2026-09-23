import assert from "node:assert/strict";
import { test } from "node:test";
import { computeBasePath } from "./basePath.ts";

test("standalone: the app is mounted at the domain root", () => {
  assert.equal(computeBasePath("/app/"), "/app");
  assert.equal(computeBasePath("/app/flow"), "/app");
  assert.equal(computeBasePath("/app/control/deep/route"), "/app");
});

test("bare /app (the redirect route itself)", () => {
  assert.equal(computeBasePath("/app"), "/app");
});

test("Home Assistant Ingress: a dynamic prefix precedes /app", () => {
  assert.equal(computeBasePath("/api/hassio_ingress/abc123/app/"), "/api/hassio_ingress/abc123/app");
  assert.equal(computeBasePath("/api/hassio_ingress/abc123/app/control"), "/api/hassio_ingress/abc123/app");
});

test("unexpected path: falls back to today's fixed behaviour", () => {
  assert.equal(computeBasePath("/"), "/app");
});
