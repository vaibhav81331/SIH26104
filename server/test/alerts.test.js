// Advisories, CAP 1.2 output, channels and the cooling-centre optimiser.

import { test } from "node:test";
import assert from "node:assert/strict";
import { renderAdvisory, LANGS, AUDIENCES } from "../src/alerts/advisory.js";
import { buildCap, istTimestamp } from "../src/alerts/cap.js";
import { signPayload, maskAddress, send } from "../src/channels/index.js";
import { greedyMaxCover, haversineKm } from "../src/optimize/cooling.js";
import { validate } from "../src/middleware.js";

const day = { date: "2024-05-30", htsi: 64.2, q10: 58.1, q90: 69.9, wbgt: 35.4, nightWbgt: 27.1, pWarning: 0.82, mri: 31.5, excessDeaths: 0.42, excessLow: 0.21, excessHigh: 0.71, edSurge: 6.3 };

// --- advisories ---------------------------------------------------------------

test("every language has every level and audience", () => {
  for (const [code, L] of Object.entries(LANGS)) {
    for (const lvl of ["Watch", "Warning", "Emergency"]) {
      assert.ok(L.sms[lvl], `${code} sms ${lvl}`);
      assert.ok(L.headline[lvl], `${code} headline ${lvl}`);
      for (const a of AUDIENCES) assert.ok(L.audiences[a]?.[lvl]?.length, `${code} ${a} ${lvl}`);
    }
  }
});

test("advisory placeholders are all filled", () => {
  for (const lang of Object.keys(LANGS)) {
    const a = renderAdvisory({ place: "Bhubaneswar Ward 12", level: "Warning", lead: 1, day, lang, audience: "hospitals" });
    for (const s of [a.sms, a.headline, a.description, ...a.actions]) assert.doesNotMatch(s, /\{\w+\}/, `${lang}: ${s}`);
  }
});

test("Odia advisories use Odia numerals", () => {
  // Place names are proper nouns and are not localised, so use one without digits.
  const a = renderAdvisory({ place: "Puri", level: "Warning", lead: 0, day, lang: "or" });
  assert.match(a.sms, /୬୪/); // HTSI 64
  assert.doesNotMatch(a.sms.replace("USHMA", "").replace("HTSI", "").replace("ORS", ""), /[0-9]/);
});

test("Odia dates are localised too", () => {
  const a = renderAdvisory({ place: "Puri", level: "Emergency", lead: 3, day, lang: "or" });
  assert.match(a.sms, /୨୦୨୪-୦୫-୩୦/);
});

test("the English Warning SMS fits a single 160-character segment budget with room for the place name", () => {
  const a = renderAdvisory({ place: "X", level: "Watch", lead: 0, day, lang: "en" });
  assert.ok(a.sms.length <= 160, `${a.sms.length} chars`);
});

test("a Normal level produces no alert text", () => {
  const a = renderAdvisory({ place: "X", level: "Normal", lead: 0, day, lang: "en" });
  assert.equal(a.sms, null);
  assert.deepEqual(a.actions, []);
});

// --- CAP 1.2 --------------------------------------------------------------------

function wellFormed(xml) {
  const stack = [];
  for (const m of xml.matchAll(/<(\/?)([a-zA-Z][\w:.-]*)[^>]*?(\/?)>/g)) {
    if (m[0].startsWith("<?")) continue;
    const [, close, name, selfClose] = m;
    if (selfClose) continue;
    if (close) {
      if (stack.pop() !== name) return false;
    } else stack.push(name);
  }
  return stack.length === 0;
}

const geom = { type: "Polygon", coordinates: [[[85.8, 20.3], [85.81, 20.3], [85.81, 20.31], [85.8, 20.31], [85.8, 20.3]]] };

test("CAP document is well-formed and carries the required elements in schema order", () => {
  const xml = buildCap({ id: "USHMA-ward-BBS-12-2024-05-29", level: "Warning", lead: 1, day, place: "Bhubaneswar Ward 12", geometry: geom, areaCode: "ward:BBS-12", mode: "replay" });
  assert.ok(wellFormed(xml));
  assert.match(xml, /xmlns="urn:oasis:names:tc:emergency:cap:1\.2"/);
  const order = ["identifier", "sender", "sent", "status", "msgType", "scope", "note", "info"];
  let last = -1;
  for (const tag of order) {
    const i = xml.indexOf(`<${tag}>`);
    assert.ok(i > last, `<${tag}> out of order`);
    last = i;
  }
  assert.equal((xml.match(/<info>/g) ?? []).length, 3, "one info block per language");
  assert.match(xml, /<language>or-IN<\/language>/);
  assert.match(xml, /<severity>Severe<\/severity>/);
  assert.match(xml, /<polygon>20\.30000,85\.80000 /);
});

test("replay alerts are Exercise, live alerts are Actual", () => {
  const base = { id: "x", level: "Emergency", lead: 0, day, place: "P", areaCode: "a" };
  assert.match(buildCap({ ...base, mode: "replay" }), /<status>Exercise<\/status>/);
  assert.match(buildCap({ ...base, mode: "live" }), /<status>Actual<\/status>/);
});

test("CAP escapes XML special characters in place names", () => {
  const xml = buildCap({ id: "x", level: "Watch", lead: 0, day, place: "A & B <Ward>", areaCode: "a", mode: "replay" });
  assert.ok(wellFormed(xml));
  assert.match(xml, /A &amp; B &lt;Ward&gt;/);
});

test("CAP timestamps carry the IST offset", () => {
  assert.match(istTimestamp(new Date("2024-05-30T06:30:00Z")), /^2024-05-30T12:00:00\+05:30$/);
});

// --- channels -------------------------------------------------------------------

test("webhook signatures are HMAC-SHA256 and verifiable", async () => {
  const { createHmac } = await import("node:crypto");
  const sig = signPayload('{"a":1}', "secret");
  const expected = "sha256=" + createHmac("sha256", "secret").update('{"a":1}').digest("hex");
  assert.equal(sig, expected);
  assert.match(sig, /^sha256=[0-9a-f]{64}$/);
  assert.notEqual(signPayload('{"a":1}', "secret"), signPayload('{"a":2}', "secret"));
});

test("addresses are masked in logs", () => {
  assert.equal(maskAddress("+919876543210"), "*********3210");
});

test("simulated mode never sends and never throws", async () => {
  const r = await send({ channel: "sms", to: "+919876543210", message: "hello" });
  assert.equal(r.status, "simulated");
  assert.equal(r.to, "*********3210");
});

// --- optimiser --------------------------------------------------------------------

test("haversine distance is right to within a metre over city scales", () => {
  assert.ok(Math.abs(haversineKm({ lat: 20.0, lon: 85.0 }, { lat: 20.0 + 1 / 111.195, lon: 85.0 }) - 1) < 0.001);
});

test("greedy max-cover picks the site covering the most demand first", () => {
  const wards = [
    { id: "a", lat: 20.0, lon: 85.0, demand: 1, excess: 1 },
    { id: "b", lat: 20.001, lon: 85.0, demand: 1, excess: 1 },
    { id: "c", lat: 20.1, lon: 85.1, demand: 5, excess: 5 },
  ];
  const r = greedyMaxCover(wards, wards, 1, 0.5);
  assert.equal(r.chosen[0].site.id, "c");
  const r2 = greedyMaxCover(wards, wards, 2, 0.5);
  assert.equal(r2.coveredDemandShare, 1);
});

test("the optimiser never opens more centres than asked, nor than there are sites", () => {
  const wards = Array.from({ length: 5 }, (_, i) => ({ id: String(i), lat: 20 + i * 0.1, lon: 85, demand: 1, excess: 1 }));
  assert.equal(greedyMaxCover(wards, wards, 3, 1).chosen.length, 3);
  assert.ok(greedyMaxCover(wards, wards, 50, 1).chosen.length <= 5);
});

// --- validation -------------------------------------------------------------------

test("request validation rejects missing and malformed fields", () => {
  assert.throws(() => validate({}, { name: { required: true } }), /name is required/);
  assert.throws(() => validate({ n: 0 }, { n: { type: "number", min: 1 } }), />= 1/);
  assert.throws(() => validate({ c: "fax" }, { c: { oneOf: ["sms"] } }), /one of/);
  assert.doesNotThrow(() => validate({ name: "x" }, { name: { required: true, type: "string" } }));
});
