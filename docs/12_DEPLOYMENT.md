# Running and Deploying

## Prerequisites

| | Version used |
| --- | --- |
| Python | 3.10 |
| Node.js | 24 LTS (≥ 20 works) |
| Disk | ~2 GB source data + ~600 MB derived |
| RAM | 8 GB comfortable (the index build peaks near 2 GB) |

## One-time build (Python)

```bash
pip install -e ".[dev]"
```

```bash
python scripts/build_all.py
```

`build_all.py` runs every stage in order and skips any whose output already exists (pass `--force` to rebuild):

| Stage | Output | Time |
| --- | --- | --- |
| Ingest 5,279 CSVs | `data/interim/hourly_grid/` | ~11 min |
| Hourly indices → daily | `data/processed/daily_cell.parquet` | ~45 min |
| Climatology + HTSI | `climatology.parquet`, `daily_htsi.parquet` | ~3 min |
| Places, mortality, NFHS-5, vulnerability, wards | `cell_district`, `baseline_mortality`, `nfhs5_districts`, `vulnerability`, `wards` | ~2 min |
| District risk | `district_risk_daily.parquet` | ~1 min |
| Forecaster training | `artifacts/forecast/` | ~90 min |
| Export | `data/serve/` | ~10 min |

## Run

```bash
cd server && npm install && npm start
```

```bash
cd dashboard && npm install && npm run build
```

Open `http://127.0.0.1:8787`. For dashboard development with hot reload, run `npm run dev` in `dashboard/` (port 5173, proxies `/v1` to the server).

## Tests

```bash
python -m pytest tests -q
```

```bash
cd server && npm test
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT`, `HOST` | 8787, 127.0.0.1 | listen address |
| `USHMA_API_KEY` | `ushma-dev-key` | key for write routes — **set this for any shared deployment** |
| `USHMA_CHANNEL_MODE` | `simulated` | `twilio` to send real SMS/WhatsApp |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_SMS_FROM`, `TWILIO_WHATSAPP_FROM` | – | Twilio credentials |
| `USHMA_WEBHOOK_SECRET` | dev value | HMAC key for webhook signatures |
| `USHMA_CAP_SENDER`, `USHMA_CAP_SENDER_NAME` | neutral placeholder | the issuing authority's CAP identity |
| `USHMA_PYTHON` | `python` | interpreter used for live refresh |
| `USHMA_RISK_CURRENT_CDR_PER_1000` etc. | see `src/ushma/config.py` | every scientific parameter is overridable |

## Operating it for real

1. Replace synthetic wards: drop `data/geo/wards.geojson` and re-run the places and export stages.
2. Schedule `python -m ushma.live` (or `POST /v1/live/refresh`) at 05:30 and 17:30 IST.
3. Set `USHMA_API_KEY`, the CAP sender, and the channel credentials; put the server behind TLS.
4. Re-train annually as a new year of reanalysis arrives.

## Cost of a state-wide rollout

The compute is small: one daily run of the live pipeline over 234 cells takes minutes on a single CPU. A 2-vCPU / 8 GB VM hosts the API and dashboard. The dominant cost is messaging: bulk SMS costs a fraction of a rupee per message, so a single broadcast to a million numbers is a substantial recurring sum. That is why subscriptions are targeted by ward, audience and minimum level rather than broadcast, and why the national cell-broadcast channel (via CAP) is the right route for population-wide Emergency alerts.
