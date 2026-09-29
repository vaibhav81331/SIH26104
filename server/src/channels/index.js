// Delivery channels behind one interface: send({ channel, to, message, meta }).
//
//   console   - logged only (default for everything in "simulated" mode)
//   webhook   - HTTP POST of the alert JSON, HMAC-SHA256 signed
//   sms       - Twilio Programmable Messaging
//   whatsapp  - Twilio WhatsApp (same API, "whatsapp:" address prefix)
//
// "simulated" mode is the default: every message is written to the delivery
// log exactly as it would be sent, nothing leaves the machine, and no
// credentials are needed. Real delivery is one environment variable away.

import crypto from "node:crypto";
import { config } from "../config.js";

const TWILIO_URL = (sid) => `https://api.twilio.com/2010-04-01/Accounts/${sid}/Messages.json`;

export function signPayload(body, secret = config.channels.webhookSecret) {
  return "sha256=" + crypto.createHmac("sha256", secret).update(body).digest("hex");
}

async function sendWebhook(to, payload) {
  const body = JSON.stringify(payload);
  const res = await fetch(to, {
    method: "POST",
    headers: { "content-type": "application/json", "x-ushma-signature": signPayload(body) },
    body,
    signal: AbortSignal.timeout(8000),
  });
  return { status: res.ok ? "sent" : "failed", providerStatus: res.status };
}

async function sendTwilio(channel, to, message) {
  const t = config.channels.twilio;
  if (!t.sid || !t.token) throw new Error("Twilio credentials not configured");
  const from = channel === "whatsapp" ? `whatsapp:${t.whatsappFrom}` : t.smsFrom;
  const dest = channel === "whatsapp" ? `whatsapp:${to}` : to;
  const res = await fetch(TWILIO_URL(t.sid), {
    method: "POST",
    headers: {
      authorization: "Basic " + Buffer.from(`${t.sid}:${t.token}`).toString("base64"),
      "content-type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ From: from, To: dest, Body: message }),
    signal: AbortSignal.timeout(10000),
  });
  const json = await res.json().catch(() => ({}));
  return { status: res.ok ? "sent" : "failed", providerId: json.sid, providerStatus: res.status };
}

/** Mask all but the last four characters of an address for logs and the UI. */
export const maskAddress = (a) => (a && a.length > 4 ? `${"*".repeat(a.length - 4)}${a.slice(-4)}` : a);

export async function send({ channel, to, message, payload }) {
  const simulated = config.channels.mode !== "twilio" && channel !== "webhook";
  try {
    if (channel === "console" || simulated) {
      return { status: "simulated", channel, to: maskAddress(to), chars: message?.length ?? 0 };
    }
    if (channel === "webhook") return { ...(await sendWebhook(to, payload)), channel, to };
    if (channel === "sms" || channel === "whatsapp") return { ...(await sendTwilio(channel, to, message)), channel, to: maskAddress(to) };
    return { status: "failed", channel, error: `unknown channel ${channel}` };
  } catch (e) {
    return { status: "failed", channel, to: maskAddress(to), error: String(e.message ?? e) };
  }
}

export const CHANNELS = ["console", "sms", "whatsapp", "webhook"];
