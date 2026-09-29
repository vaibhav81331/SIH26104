// End-to-end API test against the real exported serve bundle.
// Skipped when data/serve has not been built yet.

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { config } from "../src/config.js";

const haveBundle = fs.existsSync(path.join(config.paths.serve, "meta.json"));
let server;
let base;
let runtime;
const KEY = { "x-api-key": config.apiKey, "content-type": "application/json" };

before(async () => {
  if (!haveBundle) return;
  runtime = fs.mkdtempSync(path.join(os.tmpdir(), "ushma-test-"));
  const { createApp } = await import("../src/app.js");
  const { app } = createApp({ runtimeDir: runtime, dashboardDir: path.join(runtime, "no-dashboard") });
  await new Promise((resolve) => {
    server = app.listen(0, "127.0.0.1", resolve);
  });
  base = `http://127.0.0.1:${server.address().port}/v1`;
});

after(() => {
  server?.close();
  if (runtime) fs.rmSync(runtime, { recursive: true, force: true });
});

const get = (p) => fetch(base + p).then(async (r) => ({ status: r.status, body: r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text() }));
const post = (p, b, headers = KEY) => fetch(base + p, { method: "POST", headers, body: JSON.stringify(b) }).then(async (r) => ({ status: r.status, body: await r.json() }));

test("health and meta", { skip: !haveBundle }, async () => {
  const h = await get("/health");
  assert.equal(h.status, 200);
  assert.equal(h.body.districts, 30);
  const m = await get("/meta");
  assert.deepEqual(m.body.bands.names, ["Normal", "Watch", "Warning", "Emergency"]);
  assert.deepEqual(m.body.languages.sort(), ["en", "hi", "or"]);
});

test("snapshot covers every ward, district and cell for every lead", { skip: !haveBundle }, async () => {
  for (const lead of [0, 3, 5]) {
    const s = await get(`/snapshot?lead=${lead}`);
    assert.equal(s.status, 200);
    assert.equal(Object.keys(s.body.districts).length, 30);
    assert.ok(Object.keys(s.body.wards).length > 300);
    for (const w of Object.values(s.body.wards)) {
      assert.ok(w.q10 <= w.htsi && w.htsi <= w.q90, "band must bracket the median");
      assert.ok(w.excessLow <= w.excess + 1e-9 && w.excess <= w.excessHigh + 1e-9, "risk interval must bracket");
    }
  }
  assert.equal((await get("/snapshot?lead=9")).status, 400);
});

test("ward detail, series, explanation and advisory", { skip: !haveBundle }, async () => {
  const wards = await get("/wards");
  const id = wards.body.features[0].properties.id;
  const w = await get(`/wards/${id}`);
  assert.equal(w.body.days.length, 6);
  const s = await get(`/series/${id}?days=10`);
  assert.equal(s.body.forecast.length, 6);
  const e = await get(`/explain/${id}?lead=2`);
  assert.match(e.body.risk.sentence, /relative risk/);
  for (const lang of ["en", "hi", "or"]) {
    const a = await get(`/advisory/${id}?lang=${lang}&audience=elderly`);
    assert.equal(a.status, 200);
    assert.equal(a.body.language, lang);
  }
  assert.equal((await get("/wards/NOPE")).status, 404);
});

test("write routes need the API key", { skip: !haveBundle }, async () => {
  const r = await post("/replay/asof", { date: "2024-05-01" }, { "content-type": "application/json" });
  assert.equal(r.status, 401);
});

test("moving the replay clock forward reproduces escalations", { skip: !haveBundle }, async () => {
  const idx = await get("/replay");
  const first = idx.body.dates[0];
  await post("/replay/asof", { date: first });
  const early = await get("/alerts/active");
  await post("/replay/asof", { date: idx.body.default });
  const peak = await get("/alerts/active");
  assert.ok(peak.body.count >= early.body.count, "the default date is the season's peak risk");
  const hist = await get("/alerts/history?limit=5000");
  assert.ok(hist.body.transitions.every((t) => t.reason && t.date <= idx.body.default));
});

test("CAP XML for an active alert", { skip: !haveBundle }, async () => {
  const idx = await get("/replay");
  await post("/replay/asof", { date: idx.body.default });
  const act = await get("/alerts/active");
  if (!act.body.count) return;
  const cap = await get(`/alerts/${act.body.alerts[0].alertId}/cap.xml`);
  assert.equal(cap.status, 200);
  assert.match(cap.body, /<status>Exercise<\/status>/);
  assert.equal((cap.body.match(/<info>/g) ?? []).length, 3);
});

test("subscribe, dispatch once, dedupe on the second run", { skip: !haveBundle }, async () => {
  const idx = await get("/replay");
  await post("/replay/asof", { date: idx.body.default });
  const act = await get("/alerts/active?scope=ward");
  if (!act.body.count) return;
  const city = act.body.alerts[0].city;
  const sub = await post("/subscribe", { name: "Test officer", channel: "sms", address: "+910000000000", language: "or", audience: "municipal", cities: [city], minLevel: 1 });
  assert.equal(sub.status, 201);
  assert.equal(sub.body.address, "*********0000");
  const first = await post("/alerts/evaluate", {});
  assert.ok(first.body.dispatched.length > 0);
  assert.ok(first.body.dispatched.every((d) => d.status === "simulated"));
  const second = await post("/alerts/evaluate", {});
  assert.equal(second.body.dispatched.length, 0, "each alert goes to each subscriber once");
});

test("cooling-centre optimiser and counterfactual", { skip: !haveBundle }, async () => {
  const o = await post("/optimize/cooling-centres", { city: "Bhubaneswar", n: 6, radiusKm: 1.5 });
  assert.equal(o.status, 200);
  assert.equal(o.body.centres.length, 6);
  assert.ok(o.body.coveredRiskShare > 0 && o.body.coveredRiskShare <= 1);
  const c = await post("/counterfactual", { city: "Bhubaneswar", coolingCentres: 6, workHourShift: true, targetedAdvisories: true });
  assert.ok(c.body.averted.excess >= 0);
  assert.ok(c.body.withInterventions.excess <= c.body.baseline.excess);
  assert.equal((await post("/optimize/cooling-centres", { city: "Bhubaneswar", n: 0 })).status, 400);
});

test("field view defaults to Odia", { skip: !haveBundle }, async () => {
  const wards = await get("/wards");
  const f = await get(`/field/${wards.body.features[0].properties.id}`);
  assert.equal(f.body.lang, "or");
  assert.ok(f.body.actions.length >= 1);
});
