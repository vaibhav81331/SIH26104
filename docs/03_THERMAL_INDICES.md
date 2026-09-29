# Thermal Indices — Method, Constants and Validation

> The scientific core of USHMA. Every formula here is implemented in
> `src/ushma/indices/`, and every claim is pinned by a test in
> `tests/test_indices_reference.py`.

---

## 1. Why not just use temperature

The problem statement puts it exactly right: 40 °C at 20% humidity and 40 °C at 70% humidity are not the same event. Four variables govern human heat strain, and a dry-bulb thermometer measures one of them:

| Variable | Effect on the body | In the supplied grid |
| --- | --- | --- |
| Air temperature | Sets the convective gradient | `T2M` |
| Humidity | Determines whether sweat can evaporate — the body's only cooling route above ~35 °C | `T2MDEW`, `RH2M` |
| Wind | Drives both convective and evaporative heat loss | `WS10M` |
| Solar radiation | Direct radiant load; can add 10–20 °C to perceived stress | `ALLSKY_SFC_SW_DWN` |

All four are present hourly, plus `PS` for the barometric term. That is the full input set a physical heat-balance model needs.

---

## 2. The methodological claim: compute hourly, aggregate after

This is the single most important design decision in the project.

$$\max_{h \in \text{day}} \; \text{WBGT}(T_h, RH_h, u_h, S_h) \;\neq\; \text{WBGT}\!\left(T_{\max}, \overline{RH}, \overline{u}, \overline{S}\right)$$

The right-hand side describes **an hour that never existed**. Daily maximum temperature occurs mid-afternoon; daily *mean* relative humidity is dominated by the pre-dawn hours when RH is near 100%. Pairing them invents a hot, saturated hour that the atmosphere never produced.

The supplied `thermal_stress_index.ipynb` does exactly this, and its own output shows the consequence:

| Symptom in the supplied notebook | Value |
| --- | --- |
| Days classified "Red (Severe/Extreme)" | **9,084 of 18,265 — 49.7%** |
| Maximum WBGT | **50.0 °C** |
| Maximum Heat Index | **79.1 °C** |

A WBGT of 50 °C is not survivable by any organism; the human limit is around 35 °C. An alert that fires on half of all days carries no information and guarantees alert fatigue.

**Measured effect of the correction** (Bhubaneswar cell 20.25 °N, 85.75 °E, 2024, daily-max WBGT > 35 °C):

| Method | Days flagged | Rate |
| --- | --- | --- |
| Daily inputs → shade approximation *(supplied notebook's approach)* | 85 | **23.2%** |
| Hourly inputs → Liljegren, then daily max *(USHMA)* | 14 | **3.8%** |

A **6× reduction in over-alerting**, and note the corrected method's *peak* is higher (39.1 °C vs 37.3 °C) — this is sharper discrimination, not a uniformly cooler model.

This is asserted as a regression test: `test_hourly_indices_beat_daily_inputs_on_alert_rate`.

---

## 3. Time standard — measured, not assumed

The source files carry a bare `YYYYMMDDHH` stamp with no timezone. NASA POWER can serve hourly data in UTC *or* Local Solar Time. A wrong assumption shifts every daily maximum and every night-window by 5–6 hours.

**Method.** For each grid cell, take the irradiance-weighted centroid of the hour label across a year and compare it with astronomically computed solar noon (equation of time, Spencer 1971). The difference is the cell's UTC offset.

**Result across all 480 cells:**

| Longitude band | Cells | Measured offset | Assigned |
| --- | --- | --- | --- |
| 81.50 – 82.75 °E | 120 | +4.88 to +4.99 h | **UTC+5** |
| 83.00 – 87.25 °E | 360 | +5.86 to +6.05 h | **UTC+6** |

Maximum residual from an integer: **0.163 h (≈10 min)** — far below the 0.5 h that would make the assignment ambiguous. Every cell at a given longitude agrees, which is what physics requires since the offset depends only on longitude.

The ~0.06 h mean early bias is the expected tropical morning-clear / afternoon-cloud asymmetry pulling the irradiance centroid slightly ahead of true solar noon.

Two independent confirmations:
1. Temperature minimum falls at 05:00 IST and maximum at 13:00–14:00 IST — the textbook diurnal cycle.
2. The `T2MDEW > T2M` saturation artefact (§7) clusters at 00–06 IST peaking at 05:00, i.e. exactly at the dew-formation minimum.

Ingest asserts the peak-irradiance-hour invariant on every cell, so a future re-download in a different time standard fails loudly rather than silently corrupting the alerts.

---

## 4. Wet Bulb Globe Temperature

### 4.1 What we replaced

The supplied notebook used the Australian BOM shade approximation:

$$\text{WBGT}_{\text{shade}} = 0.567\,T + 0.393\,e + 3.94$$

It has **no wind term and no radiation term**. It cannot distinguish a breezy overcast 38 °C from a still, blazing 38 °C — which is the entire question being asked. It is retained in the codebase (`wbgt_shade`) solely as the comparison baseline.

### 4.2 What we use — Liljegren et al. (2008)

The reference method used by NIOSH and the US military. It solves two coupled heat balances:

$$\text{WBGT}_{\text{outdoor}} = 0.7\,T_{nwb} + 0.2\,T_{g} + 0.1\,T_{a}$$

**Globe temperature** $T_g$ — energy balance of a 150 mm black globe:

$$\underbrace{S_{\text{abs}}}_{\text{shortwave}} + \underbrace{\varepsilon_g\sigma\left(\tfrac{1}{2}\varepsilon_{sky}T_a^4 + \tfrac{1}{2}\varepsilon_{sfc}T_a^4\right)}_{\text{longwave in}} - \underbrace{\varepsilon_g\sigma T_g^4}_{\text{emitted}} = \underbrace{h\,(T_g - T_a)}_{\text{convection}}$$

**Natural wet bulb** $T_{nwb}$ — energy balance of a wetted wick carrying a radiative load. Unlike psychrometric wet bulb, it is exposed to sun and ambient wind, which is why outdoor WBGT responds to sunshine at all.

Both are implicit in the unknown and are solved by damped fixed-point iteration (the quartic radiative term makes an undamped step oscillate).

### 4.3 Shortwave absorption — decomposed, not fitted

Rather than a single fitted factor, each path is explicit and separately checkable (`_absorbed_shortwave`):

| Term | Mean flux over a sphere | Reason |
| --- | --- | --- |
| Direct beam | $B_n / 4$ | Sphere presents $\pi r^2$ against surface $4\pi r^2$ |
| Diffuse sky | $D / 2$ | Isotropic over the upper hemisphere |
| Ground reflection | $\alpha_{sfc}\,\text{GHI} / 2$ | Isotropic over the lower hemisphere |

**Two physical ceilings** prevent the runaway that a naive implementation produces:

1. $\text{GHI} \le 1.1\,S_0\cos z$ — global horizontal cannot exceed extraterrestrial horizontal (the 1.1 allows genuine cloud-edge enhancement).
2. $B_n \le S_0 = 1367\ \text{W m}^{-2}$ — direct normal irradiance cannot exceed the solar constant.

Without these, a low sun paired with high irradiance drives the beam term to absurd values. The first version of this function produced **87 °C WBGT** for exactly that reason.

### 4.4 Convection — forced *and* free

$$\text{Nu} = \left(\text{Nu}_{\text{forced}}^3 + \text{Nu}_{\text{free}}^3\right)^{1/3}$$

with Ranz–Marshall for forced and Churchill for free convection.

A forced-only model badly underestimates heat transfer in near-calm air and lets the globe run tens of degrees too hot — **precisely on still nights, when night-time heat stress is the thing we most need to get right.**

### 4.5 Air properties — a correctness fix worth recording

The Eucken-style form $k = (C_p + 0.25R_{air})\mu$ that appears in several published WBGT codes returns $k \approx 0.0204\ \text{W m}^{-1}\text{K}^{-1}$ at 300 K against a true value of 0.0263 — **22% low**. That drives the Prandtl number to **0.93 against air's textbook 0.70**, suppresses the convective coefficient, and leaves the globe several degrees too hot. The error is then amplified by the fourth-power inversion into mean radiant temperature.

USHMA uses standard correlations instead:

| Property | Formula | Check at 300 K |
| --- | --- | --- |
| Viscosity | Sutherland: $1.458\times10^{-6}T^{1.5}/(T+110.4)$ | 1.846e-5 ✓ |
| Conductivity | $0.02624\,(T/300)^{0.8646}$ | 0.02624 ✓ |
| **Prandtl** | $C_p\mu/k$ | **0.706** ✓ |

Pinned by test.

### 4.6 Risk bands (ISO 7243 / NIOSH)

| WBGT (°C) | Band |
| --- | --- |
| < 25 | Low |
| 25 – 28 | Moderate |
| 28 – 30 | High |
| 30 – 32 | Very High |
| ≥ 32 | Extreme |

---

## 5. Universal Thermal Climate Index

The problem statement names UTCI explicitly. The supplied notebook declared it **infeasible** on the grounds that mean radiant temperature was unavailable. With hourly irradiance plus solar geometry, Tmrt is derivable — so UTCI is computed.

### 5.1 The polynomial

UTCI's operational procedure is a 6th-order regression in $(T_a,\ T_{mrt}-T_a,\ v_{10},\ e)$ with roughly 210 coefficients. Transcribing those by hand is a well-known way to produce plausible-but-wrong values, so USHMA delegates to **`pythermalcomfort`** (a maintained implementation validated against the official reference tables) and pins it with published check values:

| $T_a$ | $T_{mrt}$ | $v$ | RH | Expected | Status |
| --- | --- | --- | --- | --- | --- |
| 30 | 50 | 1.0 | 50 | 35.5 | ✓ |
| 25 | 25 | 1.0 | 50 | 24.6 | ✓ |
| 40 | 60 | 2.0 | 70 | 55.8 | ✓ |

A library upgrade cannot silently move our numbers without failing these tests.

### 5.2 Mean radiant temperature — two of them, deliberately

This distinction matters and is easy to get wrong.

**`mean_radiant_temperature`** — inverts ISO 7726 on the black globe:

$$T_{mrt} = \left[(T_g+273)^4 + \frac{1.10\times10^8\,v^{0.6}}{\varepsilon D^{0.4}}(T_g - T_a)\right]^{0.25} - 273$$

Correct for WBGT, which is *defined* by a globe. Note $D$ must be **0.15 m** — the constant $1.10\times10^8$ is calibrated for the standard 150 mm globe, and substituting a 50 mm globe inflates the correction by a factor of 1.54.

**`mean_radiant_temperature_human`** — assembles the radiation budget of a standing person, and **this is what UTCI takes**:

| Property | Black globe | Standing human |
| --- | --- | --- |
| Shortwave absorptivity | 0.95 | **0.70** |
| Projected area factor, high sun | 0.25 | **0.134** |
| Projected area factor, low sun | 0.25 | **0.294** |

A sphere presents the same projected area from every direction; a standing person presents far less to a high sun. Feeding the globe value into UTCI inflates peak Tmrt from ~66 °C to ~95 °C and pushes the index off the top of its scale.

**Verification at clear tropical noon** (Ta 40 °C, Td 26 °C, wind 2 m/s, GHI 900 W/m², cos z 0.9):

| Quantity | Value | Published range |
| --- | --- | --- |
| Globe temperature | 57.0 °C (Ta + 17.0) | Ta + 15 to +25 ✓ |
| Tmrt (human) | **66.4 °C** | 60–75 ✓ |
| UTCI | 48.4 °C → *Extreme heat stress* | ✓ |
| WBGT | 35.8 °C | ✓ |

### 5.3 Validity domain

UTCI is fitted for $T_{mrt}-T_a \in [-30, +70]$ K and $v_{10} \in [0.5, 17]$ m/s. Inputs are clipped to that box and the clipped count is reported (`clipping_report`). Silently extrapolating a regression beyond its fitted range is how indices produce 50 °C WBGT values.

### 5.4 Official bands

| UTCI (°C) | Stress category |
| --- | --- |
| > 46 | Extreme heat stress |
| 38 – 46 | Very strong heat stress |
| 32 – 38 | Strong heat stress |
| 26 – 32 | Moderate heat stress |
| 9 – 26 | No thermal stress |

---

## 6. Heat Index

NWS Rothfusz regression, ported from the supplied notebook (whose implementation was correct) and extended with the full NOAA switching rule:

1. Compute the simple Steadman form.
2. If $(\text{HI}_{\text{simple}} + T_F)/2 < 80\ °F$, return it — the regression is invalid below that and produces nonsense.
3. Otherwise apply Rothfusz plus the low-humidity and high-humidity adjustments.

Validated against **9 points from the published NOAA chart** (±2 °F):

| T (°F) | RH (%) | Chart | | T (°F) | RH (%) | Chart |
| --- | --- | --- | --- | --- | --- | --- |
| 80 | 40 | 80 | | 96 | 50 | 108 |
| 84 | 60 | 88 | | 100 | 40 | 109 |
| 90 | 40 | 91 | | 104 | 50 | 131 |
| 90 | 60 | 100 | | 110 | 40 | 136 |
| 90 | 80 | 113 | | | | |

Heat Index accounts for temperature and humidity only — no wind, no radiation. It is retained because it is the number the public and press already recognise, not because it is sufficient.

---

## 7. Psychrometrics

**Vapour pressure from dewpoint, not RH.** The grid supplies `T2MDEW` directly; deriving vapour pressure from it avoids a round trip through RH (itself a derived, rounded quantity) and lets the disagreement between the two serve as a QC signal.

**Saturation vapour pressure** — Buck (1981), validated at six temperatures against the Smithsonian tables (0–50 °C, rel. tol. 2×10⁻³).

**Dewpoint inversion.** Buck's expression has temperature in both coefficient and exponent, so it has no closed form inverse. The usual Magnus-form shortcut drifts **~2.5% RH at high humidity** — which matters when the entire subject is humid heat. USHMA uses a Magnus starting guess refined by three Newton steps on the exact forward function; the round trip is then exact to 10⁻⁶.

**The saturation artefact.** 0.60% of supplied rows have `T2MDEW` above `T2M`:

| Property | Value |
| --- | --- |
| Rows affected (2024) | 25,226 of 4,207,536 |
| `RH2M` on those rows | **exactly 100.0, std = 0** |
| Median excess (Td − T) | 0.40 °C (max 2.21) |
| Hour of day (IST) | 00–06, peaking at 05:00 |

This is MERRA-2 rounding two near-identical saturated fields inconsistently at the pre-dawn temperature minimum, not physical supersaturation. Left alone it yields RH > 100% and pushes formulas outside their fitted domains, so `vapour_pressure` clamps dewpoint to air temperature.

**Wind height conversion.** UTCI is *defined* at 10 m and takes `WS10M` unchanged. WBGT needs wind at human height, converted by the logarithmic profile:

$$u_2 = u_{10}\,\frac{\ln(2/z_0)}{\ln(10/z_0)} = 0.72295\,u_{10} \quad (z_0 = 0.03\ \text{m})$$

floored at 0.13 m/s — Liljegren's stated lower bound, below which the globe solver has no solution.

---

## 8. Daily aggregates

Computed per cell per **IST** day (`aggregate_daily`):

| Field | Definition | Why it is there |
| --- | --- | --- |
| `*_max`, `*_mean`, `*_min` | Daily statistics of each index | Conventional |
| `*_night_min` | Minimum over 22:00–06:00 IST | **Failure of overnight recovery is among the strongest mortality predictors and is invisible to any daytime-maximum warning** |
| `wbgt_degree_hours` | $\sum_h \max(\text{WBGT}_h - 28, 0)$ | Intensity × duration in one number |
| `wbgt_hours_above_{28,30,32,35}` | Exceedance hour counts | The exposure window an outdoor worker actually faces |

Night windows are assigned to the day they **end** on, so the 22:00 reading belongs with the following morning's recovery period rather than the preceding afternoon.

---

## 9. Test inventory

`pytest tests/test_indices_reference.py` — **37 tests, all passing.**

| Group | Count | Authority |
| --- | --- | --- |
| Saturation vapour pressure | 6 | Buck 1981 / Smithsonian tables |
| Dewpoint round trip & clamping | 3 | Internal consistency |
| Wind profile | 1 | Log law, analytic |
| Heat Index | 11 | NOAA published chart |
| UTCI reference values | 3 | Bröde et al. operational procedure |
| UTCI monotonicity (wind, radiation) | 2 | Physical invariants |
| Mean radiant temperature | 2 | ISO 7726 |
| WBGT invariants & response | 5 | Physical invariants |
| WBGT bounds & robustness | 2 | Survivability limit |
| **Real-data plausibility** | 1 | Ingested 2024 panel |
| **Hourly-vs-daily alert rate** | 1 | The project's central claim, as a regression test |

---

## 10. Honest limitations

1. **Tmrt is modelled, not measured.** Both the globe and human formulations assume an open, unobstructed site with a uniform surface albedo of 0.20. Real urban geometry — shading, street canyons, wall re-radiation — changes Tmrt substantially. A proper treatment needs SOLWEIG-class modelling with building geometry.
2. **Surface albedo is a single constant.** 0.20 suits Odisha's cropland-dominated landscape but is wrong over water, sand and dense urban fabric. It should become a per-ward attribute once land-cover data is joined.
3. **Ground surface temperature is approximated by air temperature** in the longwave terms. In reality sun-baked surfaces run well above air, so the longwave load is somewhat underestimated at midday.
4. **The Erbs beam/diffuse split is a correlation**, not a measurement. It is the standard choice, but it carries real uncertainty at low sun angles.
5. **UTCI assumes a walking person at 4 km/h** with a standard metabolic rate and adaptive clothing. It is a population-average index, not a personal one.
6. **The grid is 0.25° ≈ 27 km.** These indices describe a grid cell, not a ward. Ward-level output is a documented downscaling with its own uncertainty — see `06_WARD_DOWNSCALING.md`.

---

## References

- Liljegren, J.C. et al. (2008). *Modeling the Wet Bulb Globe Temperature Using Standard Meteorological Measurements.* J. Occup. Environ. Hyg. 5(10), 645–655.
- Bröde, P. et al. (2012). *Deriving the operational procedure for the Universal Thermal Climate Index (UTCI).* Int. J. Biometeorol. 56, 481–494.
- Buck, A.L. (1981). *New equations for computing vapor pressure and enhancement factor.* J. Appl. Meteorol. 20, 1527–1532.
- Rothfusz, L.P. (1990). *The Heat Index Equation.* NWS Technical Attachment SR 90-23.
- ISO 7243:2017 — Ergonomics of the thermal environment: WBGT.
- ISO 7726:1998 — Instruments for measuring physical quantities.
- VDI 3787 Part 2 — Environmental meteorology: methods for the human-biometeorological evaluation.
- Erbs, D.G. et al. (1982). *Estimation of the diffuse radiation fraction.* Solar Energy 28, 293–302.
