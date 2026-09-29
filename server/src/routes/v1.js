// USHMA REST API, version 1. Mounted at /v1.
//
// Read routes are open (rate limited). Routes that change state, send
// messages or trigger Heat Action Plan measures require the x-api-key header.

import { Router } from "express";
import { spawn } from "node:child_process";
import path from "node:path";
import { config, ROOT } from "../config.js";
import { requireApiKey, validate } from "../middleware.js";
import { LEVELS } from "../alerts/hap.js";
import { AUDIENCES, LANGS, renderAdvisory } from "../alerts/advisory.js";
import { buildCap } from "../alerts/cap.js";
import { CHANNELS, maskAddress } from "../channels/index.js";
import { greedyMaxCover } from "../optimize/cooling.js";

const LEADS = [0, 1, 2, 3, 4, 5];
const intParam = (v, d, lo, hi) => {
  const n = Number.parseInt(v ?? d, 10);
  if (Number.isNaN(n) || n < lo || n > hi) throw Object.assign(new Error(`lead must be an integer ${lo}-${hi}`), { status: 400 });
  return n;
};

export function v1(store, db, engine) {
  const r = Router();
  const payload = () => store.payload(engine.mode, engine.asOf);
  const wardOr404 = (id) => {
    const f = store.wardIndex.get(id);
    if (!f) throw Object.assign(new Error(`unknown ward ${id}`), { status: 404 });
    return f;
  };

  // ------------------------------------------------------------------ system
  r.get("/health", (req, res) =>
    res.json({ status: "ok", mode: engine.mode, asOf: engine.asOf, wards: store.wardIndex.size, districts: store.districts.length, uptimeSeconds: Math.round(process.uptime()) }),
  );

  r.get("/meta", (req, res) => res.json({ ...store.meta, mode: engine.mode, asOf: engine.asOf, liveAvailable: !!store.live, languages: Object.keys(LANGS), audiences: AUDIENCES, channels: CHANNELS }));

  r.get("/model-card", (req, res) => {
    const f = store.validation.forecast;
    res.json({
      name: "USHMA HTSI forecaster",
      type: "LightGBM gradient-boosted trees, quantile regression (0.1/0.5/0.9) + split-conformal calibration",
      target: "Human Thermal Stress Index (0-100), daily, per 0.25 deg grid cell, D+1..D+5",
      trainedOn: "NASA POWER hourly reanalysis, Odisha, 2015-2025 (234 in-state cells)",
      split: { train: `2015-01-01..${f.train_end}`, validation: `..${f.valid_end}`, test: "2024-01-01..2025-12-31" },
      notTrainedOn: "mortality -- the supplied mortality (2007-2011) and weather (2015-2025) records share no days",
      horizons: f.horizons,
      shap: f.shap,
      intendedUse: "Anticipatory heat-health action by municipal, health and disaster-management authorities.",
      outOfScope: ["individual medical decisions", "occupational compliance certification", "areas outside Odisha without re-fitting"],
      riskModel: store.meta.exposureResponse,
      docs: "docs/10_MODEL_CARD.md",
    });
  });

  r.get("/validation", (req, res) => res.json(store.validation));

  // ------------------------------------------------------------------ replay / live
  r.get("/replay", (req, res) => res.json({ mode: engine.mode, asOf: engine.asOf, dates: store.replayDates, default: store.defaultDate, liveAvailable: !!store.live }));

  r.post("/replay/asof", requireApiKey, (req, res) => {
    validate(req.body, { date: { required: true, type: "string" } });
    engine.setAsOf(req.body.date);
    engine.emit("asof", { asOf: engine.asOf, mode: engine.mode });
    db.audit({ type: "clock", asOf: engine.asOf, by: req.body.by ?? "api" });
    res.json({ mode: engine.mode, asOf: engine.asOf, active: engine.active().length });
  });

  r.post("/live/refresh", requireApiKey, (req, res) => {
    const child = spawn(config.paths.python, ["-m", "ushma.live"], {
      cwd: ROOT,
      env: { ...process.env, PYTHONPATH: path.join(ROOT, "src") },
    });
    let log = "";
    child.stdout.on("data", (d) => (log += d));
    child.stderr.on("data", (d) => (log += d));
    child.on("close", (code) => {
      if (code === 0 && store.reloadLive()) {
        engine.setLive();
        engine.emit("asof", { asOf: engine.asOf, mode: engine.mode });
        db.audit({ type: "live-refresh", status: "ok", asOf: engine.asOf });
        res.json({ status: "ok", mode: engine.mode, asOf: engine.asOf });
      } else {
        db.audit({ type: "live-refresh", status: "failed", code });
        res.status(502).json({ status: "failed", code, log: log.split("\n").slice(-12).join("\n") });
      }
    });
  });

  r.post("/live/use", requireApiKey, (req, res) => {
    engine.setLive();
    engine.emit("asof", { asOf: engine.asOf, mode: engine.mode });
    res.json({ mode: engine.mode, asOf: engine.asOf });
  });

  // ------------------------------------------------------------------ geography
  r.get("/wards", (req, res) => res.json(store.wardsGeo));
  r.get("/cells", (req, res) => res.json(store.cellsGeo));
  r.get("/districts", (req, res) => res.json(store.districts));

  r.get("/districts/:id", (req, res) => {
    const d = store.districtIndex.get(req.params.id);
    if (!d) return res.status(404).json({ error: "unknown district" });
    res.json({ ...d, days: payload().districts[req.params.id]?.days ?? [], hap: engine.get("district", req.params.id) ?? null });
  });

  // One call for the map: every place's value at one lead time.
  r.get("/snapshot", (req, res) => {
    const lead = intParam(req.query.lead, 0, 0, 5);
    const p = payload();
    const pick = (d) => ({
      htsi: d.htsi, q10: d.q10, q90: d.q90, band: d.band, mri: d.mri, pWarning: d.pWarning,
      excess: d.excessDeaths, excessLow: d.excessLow, excessHigh: d.excessHigh, wbgt: d.wbgt, utci: d.utci,
    });
    const wards = {};
    for (const [id, w] of Object.entries(p.wards)) {
      const s = engine.get("ward", id);
      wards[id] = { ...pick(w.days[lead]), hap: s?.band ?? "Normal" };
    }
    const districts = {};
    for (const [id, d] of Object.entries(p.districts)) {
      const s = engine.get("district", id);
      districts[id] = { ...pick(d.days[lead]), htsiMax: d.days[lead].htsiMax, hap: s?.band ?? "Normal" };
    }
    const cells = Object.fromEntries(Object.entries(p.cells).map(([id, v]) => [id, v[lead]]));
    const statewide = Object.values(p.districts).reduce(
      (a, d) => ({
        excess: a.excess + (d.days[lead].excessDeaths ?? 0),
        excessLow: a.excessLow + (d.days[lead].excessLow ?? 0),
        excessHigh: a.excessHigh + (d.days[lead].excessHigh ?? 0),
      }),
      { excess: 0, excessLow: 0, excessHigh: 0 },
    );
    res.json({ mode: engine.mode, asOf: p.asOf, lead, date: p.days[lead], days: p.days, wards, districts, cells, statewide });
  });

  // ------------------------------------------------------------------ ward detail
  r.get("/wards/:id", (req, res) => {
    const f = wardOr404(req.params.id);
    const w = payload().wards[req.params.id];
    res.json({ ...f.properties, geometry: f.geometry, days: w.days, drivers: w.drivers, hap: engine.get("ward", req.params.id) ?? null });
  });

  r.get("/forecast/:id", (req, res) => {
    wardOr404(req.params.id);
    const p = payload();
    res.json({ id: req.params.id, asOf: p.asOf, mode: p.mode, days: p.wards[req.params.id].days });
  });

  // Observed history up to the as-of date, then the forecast -- the ward chart.
  r.get("/series/:id", (req, res) => {
    wardOr404(req.params.id);
    const back = intParam(req.query.days, 30, 1, 91);
    const history = [];
    if (engine.mode === "replay") {
      const idx = store.replayDates.indexOf(engine.asOf);
      for (const d of store.replayDates.slice(Math.max(0, idx - back), idx)) {
        const day = store.replay.get(d).wards[req.params.id].days[0];
        history.push({ date: d, htsi: day.htsi, band: day.band, wbgt: day.wbgt, mri: day.mri, excess: day.excessDeaths });
      }
    }
    res.json({ id: req.params.id, asOf: engine.asOf, history, forecast: payload().wards[req.params.id].days });
  });

  r.get("/explain/:id", (req, res) => {
    const f = wardOr404(req.params.id);
    const lead = intParam(req.query.lead, 1, 0, 5);
    const w = payload().wards[req.params.id];
    const day = w.days[lead];
    const hz = lead === 0 ? null : String(lead <= 1 ? 1 : lead <= 3 ? 3 : 5);
    const drivers = (hz && w.drivers?.[hz]) || [];
    const props = f.properties;
    const parts = drivers.slice(0, 3).map((d) => `${d.label} (${d.contribution >= 0 ? "+" : ""}${d.contribution.toFixed(1)} pts)`);
    const sentence =
      lead === 0
        ? `Today's observed stress in ${props.name} is ${day.htsi} (${day.band}).`
        : `The D+${lead} forecast for ${props.name} (HTSI ${day.htsi}, ${day.band}) is driven by ${parts.join(", ") || "seasonal conditions"}.`;
    res.json({
      id: props.id, lead, date: day.date, sentence,
      drivers,
      shapNote: hz && hz !== String(lead) ? `Attributions shown are from the D+${hz} model, the nearest explained horizon.` : null,
      uhi: { htsiPoints: day.uhi, builtUp: props.builtUp, sentence: `Urban heat island adds ${day.uhi} HTSI points (built-up fraction ${Math.round(props.builtUp * 100)}%).` },
      risk: {
        expectedDeaths: day.expectedDeaths, relativeRisk: day.rr, vulnerabilityMultiplier: props.vulnMult,
        population: props.population, excessDeaths: day.excessDeaths, range: [day.excessLow, day.excessHigh],
        sentence: `Expected ${Number(day.expectedDeaths).toFixed(2)} deaths/day at baseline x relative risk ${Number(day.rr).toFixed(3)} (vulnerability x${props.vulnMult} on the log scale) = ${Number(day.excessDeaths).toFixed(3)} excess.`,
      },
    });
  });

  // ------------------------------------------------------------------ alerts & advisories
  r.get("/alerts/active", (req, res) => {
    const list = engine.active({ scope: req.query.scope, city: req.query.city, minLevel: req.query.minLevel ? Number(req.query.minLevel) : 1 });
    res.json({
      mode: engine.mode, asOf: engine.asOf, count: list.length,
      counts: Object.fromEntries(LEVELS.slice(1).map((l) => [l, list.filter((s) => s.band === l).length])),
      alerts: list.map(({ transitions, ...s }) => ({ ...s, acks: s.alertId ? db.acksFor(s.alertId) : [], lastTransition: transitions.at(-1) ?? null })),
    });
  });

  r.get("/alerts/history", (req, res) => {
    const limit = intParam(req.query.limit, 200, 1, 5000);
    res.json({ asOf: engine.asOf, transitions: engine.transitions.slice(0, limit) });
  });

  r.post("/alerts/evaluate", requireApiKey, async (req, res) => {
    engine.recompute();
    const results = await engine.dispatch({ dryRun: !!req.body?.dryRun });
    db.audit({ type: "evaluate", asOf: engine.asOf, dispatched: results.length, dryRun: !!req.body?.dryRun });
    res.json({ asOf: engine.asOf, active: engine.active().length, dispatched: results });
  });

  r.get("/alerts/:alertId/cap.xml", (req, res) => {
    const rec = engine.alertRecord(req.params.alertId);
    if (!rec) return res.status(404).json({ error: "no active alert with that id" });
    const s = rec.state;
    const xml = buildCap({
      id: s.alertId, level: s.band, lead: rec.lead, day: rec.day, place: s.name,
      geometry: rec.geometry, areaCode: `${s.scope}:${s.id}`, mode: engine.mode,
    });
    res.type("application/cap+xml").send(xml);
  });

  r.get("/advisory/:id", (req, res) => {
    const lang = req.query.lang ?? "en";
    const audience = req.query.audience ?? "public";
    if (!LANGS[lang]) return res.status(400).json({ error: `lang must be one of ${Object.keys(LANGS)}` });
    if (!AUDIENCES.includes(audience)) return res.status(400).json({ error: `audience must be one of ${AUDIENCES}` });
    const isWard = store.wardIndex.has(req.params.id);
    const scope = isWard ? "ward" : "district";
    const s = engine.get(scope, req.params.id);
    if (!s) return res.status(404).json({ error: "unknown ward or district" });
    const lead = req.query.lead !== undefined ? intParam(req.query.lead, 0, 0, 5) : (s.target?.trigger?.lead ?? 0);
    const days = payload()[isWard ? "wards" : "districts"][req.params.id].days;
    res.json({ id: req.params.id, scope, hapLevel: s.band, ...renderAdvisory({ place: s.name, level: s.band, lead, day: days[lead], lang, audience }) });
  });

  // ------------------------------------------------------------------ Heat Action Plan
  r.post("/hap/trigger", requireApiKey, async (req, res) => {
    validate(req.body, {
      scope: { required: true, oneOf: ["ward", "district", "city"] },
      id: { required: true, type: "string" },
      level: { required: true, oneOf: LEVELS.slice(1) },
      by: { type: "string" },
    });
    const { scope, id, level, by = "operator", note } = req.body;
    const audiences = ["municipal", "hospitals", "power_utility", "schools"];
    const plan = Object.fromEntries(audiences.map((a) => [a, LANGS.en.audiences[a][level]]));
    // `placeId`, not `id`: the audit record owns its own id.
    const event = db.audit({ type: "hap-trigger", scope, placeId: id, level, by, note, asOf: engine.asOf, plan });
    engine.emit("hap", event);
    res.status(201).json(event);
  });

  r.post("/hap/ack", requireApiKey, (req, res) => {
    validate(req.body, { alertId: { required: true, type: "string" }, action: { required: true, type: "string" }, by: { type: "string" } });
    const a = db.ack({ alertId: req.body.alertId, action: req.body.action, by: req.body.by ?? "operator", asOf: engine.asOf });
    res.status(201).json(a);
  });

  r.get("/audit", (req, res) => res.json(db.listAudit(intParam(req.query.limit, 200, 1, 5000))));

  // ------------------------------------------------------------------ decisions
  r.post("/optimize/cooling-centres", (req, res) => {
    validate(req.body, {
      city: { required: true, type: "string" },
      n: { required: true, type: "number", min: 1, max: 60 },
      radiusKm: { type: "number", min: 0.3, max: 10 },
    });
    const { city, n } = req.body;
    const radiusKm = req.body.radiusKm ?? config.interventions.coverageRadiusKm;
    const leads = req.body.leads ?? [1, 2, 3];
    const p = payload();
    const wards = store.wardsGeo.features.filter((f) => f.properties.city === city);
    if (!wards.length) return res.status(404).json({ error: `no wards for city ${city}` });
    const demand = wards.map((f) => {
      const days = p.wards[f.properties.id].days;
      const excess = leads.reduce((s, k) => s + Math.max(0, days[k]?.excessDeaths ?? 0), 0);
      // Floor demand by exposure so centres still go somewhere sensible on a mild day.
      const floor = 1e-6 * f.properties.population * f.properties.vulnMult;
      return { id: f.properties.id, lat: f.properties.lat, lon: f.properties.lon, excess, demand: excess + floor, name: f.properties.name };
    });
    const sites = demand.map(({ id, lat, lon, name }) => ({ id, lat, lon, name }));
    const out = greedyMaxCover(demand, sites, n, radiusKm);
    const f = config.interventions.coolingCentreAvertedFraction;
    res.json({
      city, n, radiusKm, leads, asOf: p.asOf,
      method: "greedy maximal covering (lazy evaluation); worst-case within (1-1/e) of optimal",
      centres: out.chosen.map((c, i) => ({ rank: i + 1, wardId: c.site.id, name: c.site.name, lat: c.site.lat, lon: c.site.lon, newlyCoveredWards: c.wards })),
      coveredWards: out.coveredWardIds.length, totalWards: wards.length,
      coveredRiskShare: Number(out.coveredDemandShare.toFixed(3)),
      excessDeathsInCoveredWards: Number(out.coveredExcess.toFixed(3)),
      excessDeathsCity: Number(out.totalExcess.toFixed(3)),
      estimatedDeathsAverted: Number((out.coveredExcess * f).toFixed(3)),
      assumption: `Cooling-centre access averts ${Math.round(f * 100)}% of excess deaths in covered wards (configurable; an assumption, not an estimate from this data).`,
    });
  });

  r.post("/counterfactual", (req, res) => {
    validate(req.body, { city: { required: true, type: "string" } });
    const { city, coolingCentres = 0, workHourShift = false, targetedAdvisories = false } = req.body;
    const radiusKm = req.body.radiusKm ?? config.interventions.coverageRadiusKm;
    const leads = req.body.leads ?? [1, 2, 3];
    const I = config.interventions;
    const p = payload();
    const wards = store.wardsGeo.features.filter((f) => f.properties.city === city);
    if (!wards.length) return res.status(404).json({ error: `no wards for city ${city}` });
    const rows = wards.map((f) => {
      const days = p.wards[f.properties.id].days;
      const sum = (key) => leads.reduce((s, k) => s + Math.max(0, days[k]?.[key] ?? 0), 0);
      return { id: f.properties.id, lat: f.properties.lat, lon: f.properties.lon, excess: sum("excessDeaths"), low: sum("excessLow"), high: sum("excessHigh"), demand: sum("excessDeaths") + 1e-6 * f.properties.population * f.properties.vulnMult };
    });
    let covered = new Set();
    if (coolingCentres > 0) covered = new Set(greedyMaxCover(rows, rows, coolingCentres, radiusKm).coveredWardIds);
    // Effects combine multiplicatively on the remaining risk, not additively,
    // so stacking interventions cannot avert more than 100%.
    const keep = (id) =>
      (covered.has(id) ? 1 - I.coolingCentreAvertedFraction : 1) *
      (workHourShift ? 1 - I.workHourShiftAvertedFraction : 1) *
      (targetedAdvisories ? 1 - I.advisoryReachAvertedFraction : 1);
    const tot = (k) => rows.reduce((s, r) => s + r[k], 0);
    const after = (k) => rows.reduce((s, r) => s + r[k] * keep(r.id), 0);
    res.json({
      city, leads, asOf: p.asOf,
      interventions: { coolingCentres, radiusKm, workHourShift, targetedAdvisories },
      baseline: { excess: tot("excess"), low: tot("low"), high: tot("high") },
      withInterventions: { excess: after("excess"), low: after("low"), high: after("high") },
      averted: { excess: tot("excess") - after("excess"), low: tot("low") - after("low"), high: tot("high") - after("high") },
      coveredWards: covered.size,
      assumptions: {
        coolingCentreAvertedFraction: I.coolingCentreAvertedFraction,
        workHourShiftAvertedFraction: I.workHourShiftAvertedFraction,
        advisoryReachAvertedFraction: I.advisoryReachAvertedFraction,
        note: "Effect sizes are configurable planning assumptions, not quantities estimated from the supplied data.",
      },
    });
  });

  // ------------------------------------------------------------------ subscriptions & delivery
  r.get("/subscriptions", requireApiKey, (req, res) =>
    res.json(db.listSubscriptions().map((s) => ({ ...s, address: s.channel === "webhook" ? s.address : maskAddress(s.address) }))),
  );

  r.post("/subscribe", requireApiKey, (req, res) => {
    validate(req.body, {
      name: { required: true, type: "string" },
      channel: { required: true, oneOf: CHANNELS },
      address: { required: true, type: "string" },
      language: { oneOf: Object.keys(LANGS) },
      audience: { oneOf: AUDIENCES },
      minLevel: { type: "number", min: 1, max: 3 },
      wards: { type: "array" }, districts: { type: "array" }, cities: { type: "array" },
    });
    const b = req.body;
    if (!b.wards?.length && !b.districts?.length && !b.cities?.length) {
      return res.status(400).json({ error: "subscribe to at least one of wards, districts or cities" });
    }
    const sub = db.addSubscription({
      name: b.name, role: b.role ?? null, channel: b.channel, address: b.address,
      language: b.language ?? "en", audience: b.audience ?? "public", minLevel: b.minLevel ?? 1,
      wards: b.wards ?? [], districts: (b.districts ?? []).map(String), cities: b.cities ?? [],
    });
    res.status(201).json({ ...sub, address: maskAddress(sub.address) });
  });

  r.post("/webhooks", requireApiKey, (req, res) => {
    validate(req.body, { url: { required: true, type: "string" }, name: { type: "string" } });
    if (!/^https?:\/\//.test(req.body.url)) return res.status(400).json({ error: "url must be http(s)" });
    const sub = db.addSubscription({
      name: req.body.name ?? "webhook", channel: "webhook", address: req.body.url, language: "en", audience: "municipal",
      minLevel: req.body.minLevel ?? 1, wards: req.body.wards ?? [], districts: (req.body.districts ?? []).map(String), cities: req.body.cities ?? [],
    });
    res.status(201).json({ ...sub, signature: "HMAC-SHA256 of the raw body in the x-ushma-signature header" });
  });

  r.delete("/subscriptions/:id", requireApiKey, (req, res) =>
    db.removeSubscription(req.params.id) ? res.status(204).end() : res.status(404).json({ error: "unknown subscription" }),
  );

  r.get("/deliveries", requireApiKey, (req, res) => res.json(db.listDeliveries(intParam(req.query.limit, 200, 1, 5000))));

  // ------------------------------------------------------------------ field (ASHA) view
  r.get("/field/:id", (req, res) => {
    const f = wardOr404(req.params.id);
    const lang = LANGS[req.query.lang] ? req.query.lang : "or";
    const s = engine.get("ward", req.params.id);
    const days = payload().wards[req.params.id].days;
    const worst = LEADS.slice(0, 4).reduce((a, k) => (days[k].htsi > days[a].htsi ? k : a), 0);
    const adv = renderAdvisory({ place: f.properties.name, level: s?.band ?? "Normal", lead: s?.target?.trigger?.lead ?? 0, day: days[s?.target?.trigger?.lead ?? 0], lang, audience: "public" });
    res.json({
      id: req.params.id, name: f.properties.name, city: f.properties.city, asOf: engine.asOf, lang,
      level: s?.band ?? "Normal", levelLabel: adv.levelLabel,
      today: { band: days[0].band, label: LANGS[lang].levels[days[0].band], htsi: days[0].htsi },
      tomorrow: { band: days[1].band, label: LANGS[lang].levels[days[1].band], htsi: days[1].htsi },
      peak: { lead: worst, date: days[worst].date, band: days[worst].band, label: LANGS[lang].levels[days[worst].band] },
      actions: adv.actions.length ? adv.actions : (LANGS[lang].audiences.public.Watch ?? []),
      sms: adv.sms, elderlyPct: f.properties.elderlyPct, synthetic: f.properties.synthetic,
    });
  });

  // ------------------------------------------------------------------ live stream (SSE)
  r.get("/stream/alerts", (req, res) => {
    res.set({ "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
    res.flushHeaders();
    const sendEvt = (type) => (data) => res.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    const handlers = { transitions: sendEvt("transitions"), deliveries: sendEvt("deliveries"), asof: sendEvt("asof"), hap: sendEvt("hap") };
    for (const [k, h] of Object.entries(handlers)) engine.on(k, h);
    sendEvt("hello")({ asOf: engine.asOf, mode: engine.mode });
    const ping = setInterval(() => res.write(": ping\n\n"), 25_000);
    req.on("close", () => {
      clearInterval(ping);
      for (const [k, h] of Object.entries(handlers)) engine.off(k, h);
    });
  });

  return r;
}
