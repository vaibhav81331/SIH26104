// Alert engine: runs the HAP state machine for every ward and district, keeps
// the current alert set, and fans alerts out to subscribers.
//
// In replay mode the state is recomputed from the first replay day up to the
// selected as-of date, so moving the demo clock forward reproduces exactly the
// escalations and de-escalations a live deployment would have issued.

import { EventEmitter } from "node:events";
import { config } from "../config.js";
import { LEVELS, runSequence, targetLevel } from "./hap.js";
import { renderAdvisory } from "./advisory.js";
import { send } from "../channels/index.js";

function scaleThresholds(ex, k = 1) {
  if (!ex) return null;
  const cap = (x) => Math.min(0.95, x * k);
  return Object.fromEntries(
    Object.entries(ex).map(([h, v]) => [h, { warning: { threshold: cap(v.warning.threshold) }, watch: { threshold: cap(v.watch.threshold) } }]),
  );
}

export class AlertEngine extends EventEmitter {
  constructor(store, db) {
    super();
    this.store = store;
    this.db = db;
    this.mode = "replay";
    this.asOf = store.defaultDate;
    this.states = new Map();
    this.transitions = [];
    // The exceedance thresholds were tuned on the 2023 validation year by the
    // Python trainer; the engine uses them as exported, never re-derives them.
    this.hapConfig = { ...config.hap, thresholds: scaleThresholds(store.meta.exceedance, config.hap.thresholdScale) };
    this.recompute();
  }

  places() {
    const wards = this.store.wardsGeo.features.map((f) => ({
      scope: "ward", id: f.properties.id, name: f.properties.name,
      city: f.properties.city, district: f.properties.district, geometry: f.geometry,
    }));
    const districts = this.store.districts.map((d) => ({
      scope: "district", id: String(d.id), name: d.name, district: d.id, geometry: null,
    }));
    return [...wards, ...districts];
  }

  #sequence(place) {
    const bucket = place.scope === "ward" ? "wards" : "districts";
    if (this.mode === "live" && this.store.live) {
      return [{ date: this.store.live.asOf, days: this.store.live[bucket][place.id].days }];
    }
    const out = [];
    for (const d of this.store.replayDates) {
      if (d > this.asOf) break;
      const p = this.store.replay.get(d)[bucket][place.id];
      if (p) out.push({ date: d, days: p.days });
    }
    return out;
  }

  recompute() {
    const edges = this.store.bandEdges;
    const next = new Map();
    const allTransitions = [];
    for (const place of this.places()) {
      const seq = this.#sequence(place);
      if (!seq.length) continue;
      const { state, transitions, target } = runSequence(seq, edges, this.hapConfig);
      const key = `${place.scope}:${place.id}`;
      const today = seq.at(-1).days;
      next.set(key, {
        key, ...place, geometry: undefined,
        level: state.level, band: LEVELS[state.level], since: state.since,
        target, today: today[0], forecast: today.slice(1),
        alertId: state.level > 0 ? `USHMA-${place.scope}-${place.id}-${state.since}` : null,
        transitions,
      });
      for (const t of transitions) allTransitions.push({ ...t, key, scope: place.scope, id: place.id, name: place.name, city: place.city });
    }
    const previous = this.states;
    this.states = next;
    this.transitions = allTransitions.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));

    // Transitions that became visible with this recompute (the demo clock moved
    // forward, or new live data arrived) are pushed to stream subscribers.
    const fresh = [];
    for (const [key, s] of next) {
      const prev = previous.get(key);
      if (prev && prev.level !== s.level) fresh.push({ key, name: s.name, scope: s.scope, from: prev.band, to: s.band, asOf: this.asOf });
    }
    if (fresh.length) this.emit("transitions", fresh);
    return this;
  }

  setAsOf(date) {
    if (!this.store.replayDates.includes(date)) throw Object.assign(new Error(`no replay data for ${date}`), { status: 400 });
    this.mode = "replay";
    this.asOf = date;
    return this.recompute();
  }

  setLive() {
    if (!this.store.live) throw Object.assign(new Error("no live payload available"), { status: 409 });
    this.mode = "live";
    this.asOf = this.store.live.asOf;
    return this.recompute();
  }

  active({ scope, minLevel = 1, city } = {}) {
    return [...this.states.values()]
      .filter((s) => s.level >= minLevel && (!scope || s.scope === scope) && (!city || s.city === city))
      .sort((a, b) => b.level - a.level || (b.today?.mri ?? 0) - (a.today?.mri ?? 0));
  }

  get(scope, id) {
    return this.states.get(`${scope}:${id}`);
  }

  /** The alert as a CAP-ready record: which day triggered it and for where. */
  alertRecord(alertId) {
    for (const s of this.states.values()) {
      if (s.alertId === alertId) {
        const lead = s.target?.trigger?.lead ?? 0;
        const day = lead === 0 ? s.today : s.forecast[lead - 1];
        const geom = s.scope === "ward" ? this.store.wardIndex.get(s.id)?.geometry : null;
        return { state: s, lead, day, geometry: geom };
      }
    }
    return null;
  }

  /** Send the current alert for each matching place to each matching subscriber. */
  async dispatch({ dryRun = false } = {}) {
    const results = [];
    const subs = this.db.listSubscriptions();
    for (const s of this.active()) {
      const rec = this.alertRecord(s.alertId);
      for (const sub of subs) {
        const wants =
          (sub.wards?.includes(s.id) && s.scope === "ward") ||
          (sub.districts?.map(String).includes(String(s.district)) && s.scope === "district") ||
          (sub.cities?.includes(s.city) && s.scope === "ward");
        if (!wants || s.level < (sub.minLevel ?? 1)) continue;
        if (this.db.hasDelivered(s.alertId, sub.id)) continue; // dedupe: one alert, one message per subscriber
        const adv = renderAdvisory({
          place: s.name, level: s.band, lead: rec.lead, day: rec.day,
          lang: sub.language ?? "en", audience: sub.audience ?? "public",
        });
        const message = sub.channel === "whatsapp" ? `${adv.sms}\n\n• ${adv.actions.join("\n• ")}` : adv.sms;
        const payload = { alertId: s.alertId, place: s.name, scope: s.scope, level: s.band, asOf: this.asOf, mode: this.mode, advisory: adv, day: rec.day };
        const result = dryRun ? { status: "dry-run", channel: sub.channel } : await send({ channel: sub.channel, to: sub.address, message, payload });
        if (!dryRun) {
          this.db.logDelivery({ alertId: s.alertId, subscriptionId: sub.id, subscriber: sub.name, place: s.name, level: s.band, language: adv.language, message, ...result });
        }
        results.push({ alertId: s.alertId, subscriber: sub.name, ...result });
      }
    }
    if (!dryRun && results.length) this.emit("deliveries", results);
    return results;
  }
}

export { targetLevel };
