# Architecture

## Components

```
┌─────────────────────────────── Python (src/ushma) ──────────────────────────────┐
│                                                                                  │
│  ingest/nasapower ─► indices/pipeline ─► climate/climatology ─► indices/htsi     │
│   5,279 CSVs          hourly WBGT, UTCI,   per-cell day-of-year   composite       │
│   → Parquet, LST      HI, Tmrt → daily     percentiles            0-100 index     │
│                                                                                  │
│  geo/districts · geo/cells · geo/wards · geo/uhi        (places & downscaling)   │
│  health/mortality · health/nfhs · health/vulnerability  (people)                 │
│  health/risk · health/district_risk                     (heat → deaths)          │
│  forecast/model   ◄── the one trained model (LightGBM)                           │
│                                                                                  │
│  export ─► data/serve/*.json        live ─► data/serve/live/latest.json           │
└───────────────────────────────────────┬──────────────────────────────────────────┘
                                        │  JSON contract (the only coupling)
┌───────────────────────────────── Node (server/) ────────────────────────────────┐
│  data/store   read-only serve bundle, in memory                                  │
│  alerts/hap   HAP state machine  ·  alerts/engine  replay clock, dispatch        │
│  alerts/advisory (en/hi/or)  ·  alerts/cap (CAP 1.2)  ·  channels (SMS/WA/hook)   │
│  optimize/cooling (max-cover)  ·  routes/v1 (REST + SSE)  ·  data/db (runtime)   │
└───────────────────────────────────────┬──────────────────────────────────────────┘
                                        │  /v1  +  static files
                         React + Vite + Leaflet + Recharts (dashboard/)
```

## Why the split

| Concern | Lives in | Reason |
| --- | --- | --- |
| Index physics, climatology, risk, model training | Python | NumPy/pandas/LightGBM/pvlib; the science has to be testable against reference values |
| Serving, alert state, messaging, UI host | Node | Event-driven I/O (SSE, webhooks, SMS APIs) and a single JavaScript language across API and dashboard |
| Contract between them | `data/serve/` JSON | Python can be re-run on a schedule without restarting anything; Node never imports Python |

The Node server holds the whole serve bundle in memory (≈ 91 replay days × 362 places) and answers from memory, so requests are milliseconds with no database to operate. Mutable state — subscriptions, delivery log, audit trail, acknowledgements — goes to `data/runtime/db.json`, written atomically (temp file + rename).

## Train/serve parity

Replay and live payloads are produced by the same function, `export.build_payload`. Live mode runs a numerical weather forecast through the **identical** hourly index code, climatology, HTSI, downscaling and risk model that built the training data. There is no second implementation of any index anywhere.

## Replay versus live

| | Replay (default) | Live |
| --- | --- | --- |
| Weather | NASA POWER reanalysis, April–June 2024 | Open-Meteo hourly forecast, today + 5 days |
| Forecast | LightGBM D+1…D+5, trained ≤ 2022, calibrated 2023 | NWP physics; band width from the model's held-out calibration |
| CAP status | `Exercise` | `Actual` |
| Clock | Operator-controlled, can "play" day by day | Today |

## Technology choices, and what was rejected

| Choice | Rejected alternative | Why |
| --- | --- | --- |
| Liljegren WBGT | BOM shade formula | No wind or radiation term |
| `pythermalcomfort` for UTCI | Hand-typed 210-coefficient polynomial | One wrong digit is plausible and invisible |
| LightGBM quantile + conformal | Deep learning | Tabular data, 680 k rows, needs calibrated intervals and SHAP more than capacity |
| Direct multi-horizon models | Recursive one-step model | Recursive errors compound |
| Express + in-memory store | Database + ORM | Data is read-only and small; fewer moving parts |
| Server-sent events | WebSockets | One-way push is all the dashboard needs; works through proxies |
| Leaflet | MapLibre GL | Needs no style server or token; raster tiles degrade gracefully offline |
| JSON-file runtime store | Postgres | Demo-grade durability, zero setup; interface is narrow enough to swap |

## Security posture

- Write and trigger routes require `x-api-key` (constant-time compare). The default key exists only for local demos and the server warns when it is in use.
- Per-IP rate limits on reads and writes; request bodies capped at 256 KB and validated.
- Webhook payloads are HMAC-SHA256 signed; phone numbers are masked in logs and API responses.
- Channels default to **simulated** — nothing leaves the machine without explicit configuration.
- Mortality microdata never leaves Python; the API serves only derived, aggregated risk.
