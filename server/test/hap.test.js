// Heat Action Plan state machine: escalation, anticipation and anti-flapping.

import { test } from "node:test";
import assert from "node:assert/strict";
import { LEVELS, runSequence, step, targetLevel, initialState } from "../src/alerts/hap.js";

const cfg = { minDwellDays: 2, deescalationMargin: 3, anticipatoryLeadDays: 2, watchLeadDays: 5, watchProbability: 0.5 };
const edges = [48.5, 59.5, 63.5];
const bandOf = (h) => (h >= edges[2] ? "Emergency" : h >= edges[1] ? "Warning" : h >= edges[0] ? "Watch" : "Normal");
const day = (htsi, pWarning = 0, lead = 0) => ({ lead, htsi, band: bandOf(htsi), pWarning, q10: htsi - 5, q90: htsi + 5 });
const days = (hs, ps = []) => hs.map((h, k) => day(h, ps[k] ?? 0, k));

test("target level is today's observed band when the forecast is calmer", () => {
  const t = targetLevel(days([60, 40, 40, 40, 40, 40]), cfg);
  assert.equal(t.band, "Warning");
  assert.equal(t.trigger.lead, 0);
});

test("a forecast Warning tomorrow escalates today -- the system acts ahead of the heat", () => {
  const t = targetLevel(days([40, 61, 40, 40, 40, 40]), cfg);
  assert.equal(t.band, "Warning");
  assert.equal(t.trigger.lead, 1);
  assert.match(t.reason, /D\+1/);
});

test("forecasts beyond D+2 cannot declare Warning, only raise a Watch when likely", () => {
  const unlikely = targetLevel(days([40, 40, 40, 64, 40, 40], [0, 0, 0, 0.3]), cfg);
  assert.equal(unlikely.band, "Normal");
  const likely = targetLevel(days([40, 40, 40, 64, 40, 40], [0, 0, 0, 0.7]), cfg);
  assert.equal(likely.band, "Watch");
  assert.equal(likely.trigger.lead, 3);
});

test("escalation is immediate and skips levels when needed", () => {
  const { state, transition } = step(initialState("2024-05-01"), { level: 3, reason: "x", trigger: {} }, 66, "2024-05-02", edges, cfg);
  assert.equal(LEVELS[state.level], "Emergency");
  assert.equal(transition.kind, "escalate");
  assert.equal(transition.from, "Normal");
});

test("de-escalation needs dwell time and a margin below the entry edge", () => {
  const seq = [
    { date: "2024-05-01", days: days([61, 40, 40, 40, 40, 40]) }, // Warning
    { date: "2024-05-02", days: days([58, 40, 40, 40, 40, 40]) }, // below Warning edge but inside margin
    { date: "2024-05-03", days: days([57, 40, 40, 40, 40, 40]) }, // still inside margin (59.5 - 3 = 56.5)
  ];
  const r = runSequence(seq, edges, cfg);
  assert.equal(r.state.level, 2, "must hold Warning while HTSI hovers just under the edge");
});

test("de-escalation steps down one level at a time", () => {
  const seq = [
    { date: "2024-05-01", days: days([66, 40, 40, 40, 40, 40]) },
    { date: "2024-05-02", days: days([30, 30, 30, 30, 30, 30]) },
    { date: "2024-05-03", days: days([30, 30, 30, 30, 30, 30]) },
    { date: "2024-05-04", days: days([30, 30, 30, 30, 30, 30]) },
  ];
  const r = runSequence(seq, edges, cfg);
  assert.equal(LEVELS[r.state.level], "Warning", "Emergency -> Warning, not straight to Normal");
  assert.equal(r.transitions.at(-1).kind, "de-escalate");
});

test("an oscillating index does not make the alert flap", () => {
  const hs = [61, 55, 61, 55, 61, 55, 61, 55];
  const seq = hs.map((h, i) => ({ date: `2024-05-${String(i + 1).padStart(2, "0")}`, days: days([h, 40, 40, 40, 40, 40]) }));
  const r = runSequence(seq, edges, cfg);
  assert.equal(r.transitions.length, 1, `expected one escalation, got ${r.transitions.map((t) => t.kind)}`);
});

test("every transition records its reason and evidence", () => {
  const r = runSequence([{ date: "2024-05-01", days: days([40, 62, 40, 40, 40, 40]) }], edges, cfg);
  const t = r.transitions[0];
  assert.ok(t.reason && t.trigger && t.date === "2024-05-01");
});

test("a validated exceedance probability escalates even when the median stays low", () => {
  const thresholds = { 1: { watch: { threshold: 0.3 }, warning: { threshold: 0.25 } }, 2: { watch: { threshold: 0.3 }, warning: { threshold: 0.25 } } };
  const d = days([40, 45, 40, 40, 40, 40]);
  d[1].pWarning = 0.4;
  const t = targetLevel(d, { ...cfg, thresholds });
  assert.equal(t.band, "Warning");
  assert.equal(t.trigger.lead, 1);
  assert.match(t.reason, /validated trigger/);
  d[1].pWarning = 0.1;
  d[1].pWatch = 0.35;
  assert.equal(targetLevel(d, { ...cfg, thresholds }).band, "Watch");
});
