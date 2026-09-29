// Tiny durable store for the mutable state the server owns: subscriptions,
// the delivery log, the audit trail of Heat Action Plan decisions, and action
// acknowledgements. A single JSON file, written atomically (temp + rename), is
// plenty at this scale and keeps the demo dependency-free; the interface is
// narrow enough to swap for Postgres without touching callers.

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { config } from "../config.js";

const EMPTY = { subscriptions: [], deliveries: [], audit: [], acks: [] };
const MAX_LOG = 5000;

export class RuntimeDb {
  constructor(dir = config.paths.runtime) {
    this.file = path.join(dir, "db.json");
    fs.mkdirSync(dir, { recursive: true });
    this.state = fs.existsSync(this.file)
      ? { ...structuredClone(EMPTY), ...JSON.parse(fs.readFileSync(this.file, "utf8")) }
      : structuredClone(EMPTY);
  }

  #flush() {
    const tmp = `${this.file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(this.state, null, 1));
    fs.renameSync(tmp, this.file);
  }

  #append(list, entry) {
    this.state[list].push(entry);
    if (this.state[list].length > MAX_LOG) this.state[list].splice(0, this.state[list].length - MAX_LOG);
    this.#flush();
    return entry;
  }

  static id(prefix) {
    return `${prefix}_${crypto.randomBytes(6).toString("hex")}`;
  }

  // --- subscriptions -------------------------------------------------------
  listSubscriptions() {
    return this.state.subscriptions;
  }

  addSubscription(sub) {
    const rec = { id: RuntimeDb.id("sub"), createdAt: new Date().toISOString(), ...sub };
    this.state.subscriptions.push(rec);
    this.#flush();
    return rec;
  }

  removeSubscription(id) {
    const before = this.state.subscriptions.length;
    this.state.subscriptions = this.state.subscriptions.filter((s) => s.id !== id);
    this.#flush();
    return this.state.subscriptions.length < before;
  }

  // --- logs ----------------------------------------------------------------
  logDelivery(d) {
    return this.#append("deliveries", { ...d, id: RuntimeDb.id("dlv"), at: new Date().toISOString() });
  }

  hasDelivered(alertId, subscriptionId) {
    return this.state.deliveries.some((d) => d.alertId === alertId && d.subscriptionId === subscriptionId && d.status !== "failed");
  }

  listDeliveries(limit = 200) {
    return this.state.deliveries.slice(-limit).reverse();
  }

  audit(event) {
    // The generated id and timestamp are applied last so an event can never
    // overwrite them.
    return this.#append("audit", { ...event, id: RuntimeDb.id("aud"), at: new Date().toISOString() });
  }

  listAudit(limit = 200) {
    return this.state.audit.slice(-limit).reverse();
  }

  ack(a) {
    return this.#append("acks", { ...a, id: RuntimeDb.id("ack"), at: new Date().toISOString() });
  }

  acksFor(alertId) {
    return this.state.acks.filter((a) => a.alertId === alertId);
  }
}
