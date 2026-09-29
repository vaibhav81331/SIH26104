# API Reference

Base URL `http://127.0.0.1:8787/v1` (Node, `server/`). JSON unless noted. 🔑 = requires `x-api-key`.

Reads are rate-limited to 600/min per IP, writes to 60/min. Errors are `{ "error": "..." }` with a 4xx/5xx status.

## System

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/health` | status, mode, as-of, counts |
| GET | `/meta` | band edges, HTSI weights, risk-curve parameters, replay window, languages, audiences, channels |
| GET | `/model-card` | machine-readable model card: target, split, per-horizon metrics, SHAP, intended/out-of-scope use |
| GET | `/validation` | every number on the Evidence page |

## Clock

| Method | Path | Body | Effect |
| --- | --- | --- | --- |
| GET | `/replay` | – | available dates, current as-of, mode |
| POST 🔑 | `/replay/asof` | `{ "date": "2024-05-30" }` | moves the demo clock; alert states are recomputed from the first replay day |
| POST 🔑 | `/live/refresh` | – | runs `python -m ushma.live` (Open-Meteo), then switches to live mode |
| POST 🔑 | `/live/use` | – | switches to the last live payload |

## Places and forecasts

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/wards` · `/cells` | GeoJSON |
| GET | `/districts` · `/districts/:id` | district profile, vulnerability, D+0…D+5, HAP state |
| GET | `/snapshot?lead=0..5` | every ward, district and cell at one lead — HTSI, band, MRI, excess deaths (+range), HAP level, statewide total |
| GET | `/wards/:id` | ward attributes, geometry, D+0…D+5, SHAP drivers, HAP state |
| GET | `/forecast/:id` | D+0…D+5 only |
| GET | `/series/:id?days=30` | observed history up to as-of, then the forecast |
| GET | `/explain/:id?lead=1` | plain-language explanation: SHAP drivers, UHI contribution, risk decomposition |

Each day record (illustrative values):

```json
{ "date": "2024-05-31", "lead": 1, "observed": false,
  "htsi": 64.1, "q10": 57.9, "q90": 69.8, "pWarning": 0.86, "band": "Emergency",
  "wbgt": 35.2, "utci": 47.5, "nightWbgt": 27.4, "uhi": 4.1,
  "rr": 1.2143, "mri": 42.9, "expectedDeaths": 0.2711,
  "excessDeaths": 0.058, "excessLow": 0.029, "excessHigh": 0.098, "edSurge": 0.87 }
```

## Alerts and advisories

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/alerts/active?scope=ward\|district&city=&minLevel=1` | current HAP levels ≥ Watch, ranked, with reason, trigger, acknowledgements |
| GET | `/alerts/history?limit=200` | level transitions, newest first, each with reason and evidence |
| POST 🔑 | `/alerts/evaluate` | `{ "dryRun": false }` — recompute and dispatch to subscribers (deduplicated per alert per subscriber) |
| GET | `/alerts/:alertId/cap.xml` | **CAP 1.2** document, one `<info>` per language (en-IN, hi-IN, or-IN) |
| GET | `/advisory/:id?lang=en\|hi\|or&audience=public&lead=` | headline, SMS, description, actions |

Audiences: `public`, `elderly`, `outdoor_workers`, `schools`, `hospitals`, `power_utility`, `municipal`.

## Heat Action Plan

| Method | Path | Body |
| --- | --- | --- |
| POST 🔑 | `/hap/trigger` | `{ "scope": "ward\|district\|city", "id": "BBS-12", "level": "Warning", "by": "commissioner", "note": "" }` → audit event with the per-agency action plan |
| POST 🔑 | `/hap/ack` | `{ "alertId": "...", "action": "Open cooling centres in priority wards", "by": "ward officer" }` |
| GET | `/audit?limit=200` | decisions, triggers, clock changes |

## Decisions

```http
POST /v1/optimize/cooling-centres
{ "city": "Bhubaneswar", "n": 8, "radiusKm": 1.5, "leads": [1, 2, 3] }
```
Greedy maximal covering over forecast excess deaths. Returns ranked sites, wards covered, share of risk covered, projected deaths averted, and the assumption used.

```http
POST /v1/counterfactual
{ "city": "Cuttack", "coolingCentres": 10, "workHourShift": true, "targetedAdvisories": true }
```
Baseline vs with-interventions excess deaths over D+1…D+3 with low/high range. Effects combine multiplicatively on the remaining risk.

## Subscriptions and delivery 🔑

| Method | Path | Body |
| --- | --- | --- |
| POST | `/subscribe` | `{ "name", "channel": "sms\|whatsapp\|webhook\|console", "address", "language", "audience", "minLevel": 1-3, "wards": [], "districts": [], "cities": [] }` |
| POST | `/webhooks` | `{ "url": "https://…", "cities": ["Puri"] }` — payloads signed `x-ushma-signature: sha256=<HMAC of body>` |
| GET | `/subscriptions` | addresses masked |
| DELETE | `/subscriptions/:id` | |
| GET | `/deliveries?limit=` | delivery log |

Channels are **simulated** unless `USHMA_CHANNEL_MODE=twilio` and the Twilio variables are set; webhooks are real in every mode.

## Field and stream

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/field/:wardId?lang=or` | compact ward summary for the ASHA view |
| GET | `/stream/alerts` | server-sent events: `hello`, `transitions`, `deliveries`, `asof`, `hap` |

## Examples

```bash
curl -s localhost:8787/v1/alerts/active?scope=district | jq '.counts'
```

```bash
curl -s -X POST localhost:8787/v1/replay/asof -H "x-api-key: ushma-dev-key" -H "content-type: application/json" -d '{"date":"2024-05-30"}'
```

```bash
curl -s "localhost:8787/v1/advisory/BBS-12?lang=or&audience=elderly" | jq -r '.sms'
```
