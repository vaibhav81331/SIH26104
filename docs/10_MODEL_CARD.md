# Model Card — USHMA Thermal-Stress Forecaster

Machine-readable version: `GET /v1/model-card`. Full metrics: [11_VALIDATION_REPORT.md](11_VALIDATION_REPORT.md) (generated).

## What it is

| | |
| --- | --- |
| Task | Forecast the Human Thermal Stress Index (0–100) for each 0.25° grid cell, 1–5 days ahead, and the probability of Watch-or-worse and Warning-or-worse days |
| Models | Per lead time: LightGBM quantile regressors (τ = 0.1, 0.5, 0.9), split-conformal calibration of the 80% band, LightGBM binary exceedance classifiers (Watch+, Warning+), and point regressors for WBGT, UTCI and night WBGT used in ward downscaling — 40 models in all |
| Inputs | Issuance-day indices and lags (1, 2, 3, 6 days), 3/7/14-day rolling means, 7-day max, spell length, target-day climatology, seasonal harmonics, latitude and longitude — 44 features, all known at issuance |
| Training data | NASA POWER hourly reanalysis, 234 in-state cells, via the hourly index pipeline |
| Split | Train 2015–2022 · calibrate and tune thresholds 2023 · **test 2024–2025, untouched until scoring** |
| **Not trained on** | Mortality. The supplied mortality (2007–2011) and weather (2015–2025) records share no days. Deaths are computed downstream by a transparent risk model. |

## How well it works (held-out 2024–2025)

**Point forecast** — mean absolute error in HTSI points:

| Lead | Model | Persistence | Climatology |
| --- | --- | --- | --- |
| D+1 | **3.51** | 4.45 | 4.91 |
| D+3 | **4.16** | 6.14 | 4.91 |
| D+5 | **4.27** | 6.67 | 4.91 |

It beats both baselines at every lead; its margin over climatology narrows with lead, as it must for a history-only forecaster.

**Uncertainty** — share of outcomes inside the stated 80% band: raw quantiles 68–72%; **after conformal calibration 78.5–79.3%**.

**Dangerous days** — Warning-or-worse is 1.1% of test days:

| Lead | AUC | F1 | Persistence F1 |
| --- | --- | --- | --- |
| D+1 | 0.929 | **0.26** | 0.18 |
| D+3 | 0.893 | **0.11** | 0.06 |
| D+5 | 0.882 | **0.11** | 0.07 |

The classifiers rank risk well (AUC 0.88–0.93) and roughly double persistence's F1, but absolute precision and recall for this rare class are modest. That is the reason the Heat Action Plan escalates on *probability against a validated threshold* for D+1–D+2 and treats D+3–D+5 only as a Watch heads-up.

**A failure we found and fixed.** The quantile median never forecast a single Warning day on the test years (F1 = 0 at every lead): median regression shrinks toward typical values. Driving alerts from the median would have produced a system that is accurate on average and silent when it matters. The exceedance classifiers exist because of this.

## What drives it

Top D+1 features by mean |SHAP|: today's peak UTCI, today's thermal stress, normal stress for the target date, today's maximum temperature, and time of year. The forecaster leans on persistence plus climatology — which is what a history-only model of a smooth field should do.

## Intended use

Anticipatory heat-health action by municipal, health and disaster-management authorities: when to open cooling centres, prepare hospitals, move working hours, and whom to message.

## Out of scope

- Individual medical decisions.
- Occupational compliance certification (use measured WBGT on site).
- Places outside Odisha without re-fitting the climatology, bands and models.
- Any claim about deaths in a particular ward on a particular day: excess-death figures are expected values with ranges.

## Known limitations

- History-only in replay; beyond D+2 skill over climatology is small. Live mode uses numerical weather prediction instead, with band widths borrowed from this model's calibration.
- 27 km resolution; ward values are downscaled.
- Ward exceedance probabilities are interpolated cell probabilities, not shifted for the urban heat island, so they are conservative for dense wards.
- Trained on 8 years; a changing climate shifts the baseline, so the model and climatology should be refitted annually.

## Fairness

Errors are not uniform: the model is trained on grid cells, and small, urban and coastal places are the most smoothed. The vulnerability layer deliberately raises risk for elderly, chronically ill, low-capacity and slum populations so that uncertainty is resolved in their favour.
