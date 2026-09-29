// Central configuration for the USHMA server. Everything tunable is here and
// overridable by environment variable, so a deployment never needs a code edit.

import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(here, "..", "..");

const num = (v, d) => (v === undefined || v === "" ? d : Number(v));

export const config = {
  port: num(process.env.PORT, 8787),
  host: process.env.HOST ?? "127.0.0.1",

  paths: {
    serve: process.env.USHMA_SERVE_DIR ?? path.join(ROOT, "data", "serve"),
    runtime: process.env.USHMA_RUNTIME_DIR ?? path.join(ROOT, "data", "runtime"),
    dashboard: process.env.USHMA_DASHBOARD_DIR ?? path.join(ROOT, "dashboard", "dist"),
    python: process.env.USHMA_PYTHON ?? "python",
  },

  // Write and trigger routes require this key in the `x-api-key` header.
  // The default exists only so a local demo works out of the box; the server
  // logs a warning whenever it is in use.
  apiKey: process.env.USHMA_API_KEY ?? "ushma-dev-key",

  rateLimit: {
    windowMs: 60_000,
    read: num(process.env.USHMA_RATE_READ, 600),
    write: num(process.env.USHMA_RATE_WRITE, 60),
  },

  // Heat Action Plan state machine. Mirrors src/ushma/config.py AlertSettings;
  // band edges themselves are read from the exported meta.json so Python and
  // Node can never disagree about what "Warning" means.
  // Operating point chosen by sweeping the April-June 2024 replay season
  // (docs/09_ALERTING_AND_HAP.md). The first settings -- F1-optimal classifier
  // thresholds, D+1..D+2 escalation, a 3-point clearance margin -- held wards
  // at Warning+ on 44.8% of ward-days against 10.7% observed: alert fatigue by
  // construction. This point gives 28.4%, still pre-warns 94% of observed
  // Warning days with at least a Watch the day before, and changes level less
  // often than either the old setting or a plain thermometer.
  hap: {
    minDwellDays: num(process.env.USHMA_HAP_MIN_DWELL, 2),
    deescalationMargin: num(process.env.USHMA_HAP_DEESC_MARGIN, 1.0),
    anticipatoryLeadDays: num(process.env.USHMA_HAP_LEAD, 1), // D+1 forecast can raise the level
    watchLeadDays: 5, // D+2..D+5: a likely Warning raises at most a Watch
    watchProbability: 0.5,
    // Classifier thresholds were tuned for F1 on single cell-days. An alert
    // compounds that decision over several lead days and a hysteresis hold,
    // so the HAP uses a more precise operating point than F1-optimal.
    thresholdScale: num(process.env.USHMA_HAP_THRESHOLD_SCALE, 2),
  },

  // Intervention effect sizes for the counterfactual panel. These are
  // ASSUMPTIONS, stated as such in the API response and the docs.
  interventions: {
    coolingCentreAvertedFraction: 0.15, // share of excess deaths averted in covered wards
    workHourShiftAvertedFraction: 0.08, // outdoor work moved out of 11:00-16:00
    advisoryReachAvertedFraction: 0.05, // targeted SMS/WhatsApp to vulnerable households
    coverageRadiusKm: 1.5, // walking distance to a cooling centre
  },

  channels: {
    // "simulated" by default: every message is logged, nothing leaves the
    // machine, no credentials needed. Set USHMA_CHANNEL_MODE=twilio with the
    // Twilio variables below to send real SMS / WhatsApp.
    mode: process.env.USHMA_CHANNEL_MODE ?? "simulated",
    twilio: {
      sid: process.env.TWILIO_ACCOUNT_SID,
      token: process.env.TWILIO_AUTH_TOKEN,
      smsFrom: process.env.TWILIO_SMS_FROM,
      whatsappFrom: process.env.TWILIO_WHATSAPP_FROM,
    },
    webhookSecret: process.env.USHMA_WEBHOOK_SECRET ?? "ushma-webhook-dev-secret",
  },

  cap: {
    // A neutral placeholder: a real deployment sets the issuing authority's own
    // sender identity here. The demo must never look like an official source.
    sender: process.env.USHMA_CAP_SENDER ?? "alerts@ushma-demo.example.org",
    senderName: process.env.USHMA_CAP_SENDER_NAME ?? "USHMA Heat-Health Early Warning (demonstration)",
  },
};
