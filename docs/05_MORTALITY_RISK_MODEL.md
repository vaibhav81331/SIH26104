# Mortality Risk Model

> `src/ushma/health/`. The curve parameters are in `config/exposure_response.yaml`.

## 1. The constraint that decides everything

| Dataset | Years |
| --- | --- |
| AHS mortality microdata | 2007–2011 |
| NASA POWER hourly weather | 2015–2025 |
| **Overlap** | **none** |

A heat→mortality curve cannot be estimated from these two files. So the model is built in two explicit halves:

| Term | Source | Status |
| --- | --- | --- |
| Baseline deaths by district and day of year | AHS 2007–2011, de-duplicated | **fitted locally** |
| Population | Census 2011 × growth factor | local |
| Vulnerability multiplier | HVI remote sensing + NFHS-5 | **fitted locally** |
| Heat exposure–response | Literature ranges, tropical South/South-East Asia | **transferred**, cited, swappable |

No machine learning happens in this stage, by design.

## 2. Composition

$$\text{excess}(w,t) = \underbrace{b(d,\text{doy})}_{\text{baseline rate}} \times \underbrace{P(w)}_{\text{population}} \times \big[RR_w(t) - 1\big]$$

$$\log RR_w(t) = v(w)\cdot\beta\sum_{l=0}^{3} \lambda_l \max\!\big(\text{HTSI}_{t-l} - h_0,\,0\big)$$

| Symbol | Value | Meaning |
| --- | --- | --- |
| $h_0$ | 48.5 | Threshold = HTSI Watch edge (~p90 of summer days) |
| $\beta$ | from $RR(63.6) = 1.20$ | Relative risk at the summer 99th percentile |
| $\lambda$ | 0.50, 0.25, 0.15, 0.10 | Lag weights, days 0–3 |
| $v(w)$ | 0.75 – 1.35 | Vulnerability multiplier, applied on the **log** scale |
| cap | 1.8 | Maximum RR before vulnerability |
| interval | $RR(63.6) \in [1.10, 1.35]$ | Carried through every number as low/high |

Vulnerability modifies risk on the log scale — effect modification — so a more vulnerable ward raises the exponent rather than simply multiplying deaths.

Outputs per ward and district per day: relative risk, **Mortality Risk Index** $=100\,(RR-1)/0.5$ clipped to 0–100, expected and excess deaths with interval, and an emergency-department surge estimate (15 visits per excess death, range 8–25 — a stated assumption).

## 3. Baseline from the AHS survey

1. **De-duplication.** Survey rounds 1 and 2 repeat the same 23,269 deaths in 14 districts (identical household, member serial, sex, date and age). Removed first. State crude death rate for 2007–09 falls from 10.3 to **6.97 per 1,000** — plausible.
2. **District level** = median of each district's own non-zero yearly weighted totals (coverage differs by district: some rounds reach only 2010–11). Relative rates bounded to [0.7, 1.4] because a few thinly surveyed districts (Kandhamal: 2.2/1,000) would otherwise drive threefold differences in risk.
3. **Anchor** today's statewide level to a configurable crude death rate (7.3/1,000, approximate SRS); AHS supplies relative structure only.
4. **Seasonality** = 2-harmonic Fourier fit to weighted monthly deaths. The raw profile peaks in **January and August**, not in the heat season — reported as found (winter cardiorespiratory, monsoon infection, recall bias).

## 4. Three corrections made while validating

| Symptom | Cause | Fix |
| --- | --- | --- |
| ~860 heat deaths attributed to Dec–Jan | Anomaly channel scored warm *winter* days highly | Anomaly & duration gated on daily-max WBGT 27 → 31 °C |
| UTCI gate did not help | A person in midday sun reaches UTCI ~34 even in January | Gate on WBGT instead |
| 19 Oct 2024 (30 °C) outranked 30 May 2024 (42.5 °C) | Relative channels (0.40 weight) outvoted absolute load | Intensity weight raised to 0.50 |

After these, attributed deaths peak in **May**, and December–January carry under 2%. This is pinned by `test_attributed_deaths_follow_the_heat_season`.

## 5. Results (district-level, 2015–2025)

| Year | Attributable deaths | Range | % of all deaths |
| --- | --- | --- | --- |
| 2021 | 797 | 412 – 1,332 | 0.2 |
| 2023 | 1,506 | 775 – 2,531 | 0.4 |
| **2024** | **1,933** | 996 – 3,249 | 0.6 |

**NCRB check (2023):** 1,506 attributable against **73** certified heatstroke deaths — a ratio of ~21. Certified heatstroke is a small, under-ascertained subset of heat-attributable all-cause mortality; a gap of one to two orders of magnitude is what the literature leads you to expect. This is a plausibility check, not calibration.

## 6. The upgrade path

`fit_local()` is the missing piece that a paired weather–mortality series (e.g. daily civil-registration deaths for 2015–2025) would unlock: a distributed-lag non-linear model estimating $\beta$, $h_0$ and $\lambda$ from Odisha data, replacing the YAML. Nothing else in the pipeline changes.
