// Cross-cutting HTTP concerns: API-key auth on write routes, rate limiting,
// and uniform error responses.

import crypto from "node:crypto";
import { config } from "./config.js";

/** Constant-time comparison, so the key cannot be recovered by timing. */
function safeEqual(a, b) {
  const x = Buffer.from(String(a ?? ""));
  const y = Buffer.from(String(b ?? ""));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}

export function requireApiKey(req, res, next) {
  if (safeEqual(req.get("x-api-key"), config.apiKey)) return next();
  res.status(401).json({ error: "unauthorised", detail: "send a valid x-api-key header" });
}

/** Fixed-window limiter per client IP, separate budgets for reads and writes. */
export function rateLimit() {
  const hits = new Map();
  setInterval(() => hits.clear(), config.rateLimit.windowMs).unref();
  return (req, res, next) => {
    const write = req.method !== "GET" && req.method !== "HEAD";
    const key = `${req.ip}:${write ? "w" : "r"}`;
    const n = (hits.get(key) ?? 0) + 1;
    hits.set(key, n);
    const limit = write ? config.rateLimit.write : config.rateLimit.read;
    res.set("x-ratelimit-limit", String(limit));
    res.set("x-ratelimit-remaining", String(Math.max(0, limit - n)));
    if (n > limit) return res.status(429).json({ error: "rate limited", retryAfterSeconds: 60 });
    next();
  };
}

export function notFound(req, res) {
  res.status(404).json({ error: "not found", path: req.path });
}

// eslint-disable-next-line no-unused-vars
export function errorHandler(err, req, res, next) {
  const status = err.status ?? 500;
  if (status >= 500) console.error("[ushma]", err);
  res.status(status).json({ error: status >= 500 ? "internal error" : err.message });
}

/** Tiny body validator: required keys and simple types, no dependency. */
export function validate(body, schema) {
  const errors = [];
  for (const [k, rule] of Object.entries(schema)) {
    const v = body?.[k];
    if (v === undefined || v === null || v === "") {
      if (rule.required) errors.push(`${k} is required`);
      continue;
    }
    if (rule.type === "array" && !Array.isArray(v)) errors.push(`${k} must be an array`);
    else if (rule.type && rule.type !== "array" && typeof v !== rule.type) errors.push(`${k} must be a ${rule.type}`);
    if (rule.oneOf && !rule.oneOf.includes(v)) errors.push(`${k} must be one of ${rule.oneOf.join(", ")}`);
    if (rule.min !== undefined && typeof v === "number" && v < rule.min) errors.push(`${k} must be >= ${rule.min}`);
    if (rule.max !== undefined && typeof v === "number" && v > rule.max) errors.push(`${k} must be <= ${rule.max}`);
  }
  if (errors.length) throw Object.assign(new Error(errors.join("; ")), { status: 400 });
}
