# Problem and Approach

## The problem, in one line

Heat warnings in India are issued on air temperature. Heat kills through the **body's heat balance** — temperature, humidity, wind and sunshine together, over the day *and the night*. USHMA forecasts the second thing and turns it into decisions.

## Requirement traceability

Every requirement in `PS.txt`, where it is met, and how it is proven.

| # | Requirement (from the problem statement) | Where it lives | Evidence |
| --- | --- | --- | --- |
| 1 | Comprehensive **Human Thermal Stress Index** integrating temperature, humidity, wind and radiation | `indices/` → HTSI in `indices/htsi.py` | 37 reference-value tests; [04_HTSI_SPEC](04_HTSI_SPEC.md) |
| 2 | Advanced metrics — **WBGT, UTCI, Heat Index** — not temperature alone | `indices/wbgt.py` (Liljegren), `indices/utci.py`, `indices/heat_index.py` | NOAA chart, UTCI reference values, ISO 7726, Buck tables |
| 3 | Automated **Mortality Risk Index** linked to the stress index | `health/risk.py`, `health/district_risk.py` | Seasonality regression test; NCRB comparison |
| 4 | Integrate **historical public health, demographic and weather data** | `health/mortality.py` (AHS), `health/nfhs.py` (NFHS-5), `health/vulnerability.py` (HVI + NFHS), `ingest/nasapower.py` | [02_DATA_DICTIONARY](02_DATA_DICTIONARY.md) |
| 5 | **Elderly / outdoor-worker density** | Vulnerability sensitivity pillar; ward elderly/slum shares; outdoor-worker advisories | [05_MORTALITY_RISK_MODEL](05_MORTALITY_RISK_MODEL.md) |
| 6 | Predict mortality and hospitalisation spikes **3–5 days in advance** | `forecast/model.py` — LightGBM D+1…D+5, conformal intervals → risk model → excess deaths + ED surge | Held-out 2024–25 backtest, [11_VALIDATION_REPORT](11_VALIDATION_REPORT.md) |
| 7 | **Dynamic GIS dashboard**, colour-coded, **ward/zone level** | `dashboard/` (React + Leaflet) | Map, lead slider, ward drill-down |
| 8 | **Actionable, automated public-health advisories** | `server/src/alerts/advisory.js` + `i18n/{en,hi,or}.json` — 7 audiences × 3 levels × 3 languages | Node tests |
| 9 | **API** pushing **SMS / WhatsApp** regional alerts | `server/src/channels/` (simulated by default, Twilio adapter), webhooks, subscriptions | [07_API_REFERENCE](07_API_REFERENCE.md) |
| 10 | **Triggers** for heat action plans — cooling centres, power grids, outdoor work hours | HAP state machine (`alerts/hap.js`), `/v1/hap/trigger`, per-audience action catalogue incl. power utility, cooling-centre optimiser | [09_ALERTING_AND_HAP](09_ALERTING_AND_HAP.md) |

## What we found in the supplied material

Before building, we audited the inputs. Four problems shaped the design:

| # | Finding | Consequence if ignored | What we did |
| --- | --- | --- | --- |
| 1 | The supplied notebook pairs **daily-max temperature with daily-mean humidity** | 49.7% of days "Red"; WBGT up to 50 °C (unsurvivable) | Indices computed **hourly**, then aggregated |
| 2 | Mortality (2007–11) and weather (2015–25) **share no days** | Any "trained mortality model" is impossible or leaked | Risk curve transferred and labelled; the ML model forecasts stress |
| 3 | **23,269 death records duplicated** across survey rounds in 14 districts | Mortality doubled in exactly those districts | De-duplicated on the decedent key |
| 4 | Four HVI columns are a **national fallback, identical for all 30 districts** | Vulnerability flat on half its inputs | Replaced with NFHS-5 district data parsed from `Odisha.pdf` |

Plus one fact we measured rather than assumed: the weather files are in **local time with a one-hour step at 82.875 °E** (UTC+5 west, UTC+6 east), not UTC.

## The approach

```
hourly weather ─► physics (WBGT, UTCI, HI) ─► HTSI ─► ML forecast D+1..5 ─► risk model ─► HAP levels ─► actions & messages
   (46 M rows)      tested against references   calibrated     conformal bands      transparent     no flapping     CAP 1.2, SMS
```

Two principles run through it:

- **Learned where the data supports learning, transparent everywhere else.** The only trained model predicts thermal stress, which the data labels 46 million times over. Deaths are computed by a product of named, inspectable terms.
- **Say what you don't know.** Every transferred parameter, synthetic layer and assumption is labelled in the data, the API responses and the UI.
