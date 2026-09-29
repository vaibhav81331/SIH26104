# USHMA — Heat-Health Early Warning System (SIH)

> **U**rban **S**ystem for **H**eat-stress **M**onitoring & **A**lerting
> *"Forecasting not what the weather will be, but what the weather will do."*

---

## Context

`PS.txt` asks for a localized, impact-based heatwave early-warning system that:

1. Computes a **Human Thermal Stress Index** integrating temperature, humidity, wind and radiation (WBGT / UTCI / HI — not temperature alone).
2. Links it to an automated **Mortality Risk Index** using historical health, demographic and weather data.
3. Forecasts **heat-induced mortality and hospitalization spikes 3–5 days in advance**.
4. Serves a **dynamic GIS dashboard** with colour-coded, hyper-local (ward/zone) alerts and automated public-health advisories.
5. Exposes an **API** that pushes SMS/WhatsApp alerts and triggers city heat-action plans (cooling centres, grid load, work-hour shifts).

### What already exists in the folder

| Asset | State |
| --- | --- |
| `nasapower_odisha/` | **5,279 hourly CSVs ≈ 2.0 GB**, `{lat}_{lon}_{year}.csv`. **480 grid points on a complete 0.25° lattice** (lat 17.50–22.25 × lon 81.50–87.25), **2015–2025**, ~46 M station-hours. Columns: `T2M, RH2M, T2MDEW, PS, WS10M, ALLSKY_SFC_SW_DWN`, indexed `YYYYMMDDHH`. No `-999` fills, no header preamble, header byte-identical across all files. One file missing: `20.0_83.5_2024.csv`. **The mandated training source.** |
| `master_weather_odisha.csv` | 18,265 rows = 5 districts × daily 2015-01-01→2024-12-31. Derived, **daily** aggregate. |
| `master_weather_odisha_thermal.csv` | Output of `thermal_stress_index.ipynb` — HI, WBGT, AT, risk band. |
| `thermal_stress_index.ipynb` | Computes HI (Rothfusz), WBGT (BOM shade approx.), Apparent Temp (BOM). No ML, no UTCI. Hardcoded `C:\Users\karim\...` paths; won't run here. |
| `constraints.ipynb` | 6 lines: subsets national HVI to 5 Odisha districts. |
| `mort_21_Odisha.csv` (26 MB) | **Pipe-delimited**, 94,619 individual death records × 122 cols — AHS Mortality Schedule, Odisha. All 30 districts (codes 1–30). **2007–2011 only.** 49,259 rows (52.1%) have an exact day; the rest have day = 0. No ICD codes, **no heat-stroke cause code**. Survey-weighted (`wt`). Untouched by both notebooks. |
| `india_district_hvi_final.csv` | 793 districts × 31 cols. Remote-sensing columns (LST, NDVI, built-up, night lights, healthcare travel time) are real; **`mpi_poverty_pct`, `literacy_pct`, `outdoor_workers_pct`, `sc_st_pct` are a national fallback block, identical across all 30 Odisha districts** — zero within-state variation. |
| `odisha_5districts_hvi.csv` | Straight 5-row subset. Note these are *not* Odisha's 5 most vulnerable — Jajapur (80.46) and Bhadrak (80.43) outrank several of them. |
| `Data_structure_AHS.xlsx` | The official AHS codebook — 7 sheets, incl. the state/district code decoder and the 129-field MORT dictionary. **This is the key that makes the mortality file readable.** |
| `NCRB_ADSI_2023.pdf` | Accidental Deaths & Suicides in India 2023. Table 1.9 p.37 gives state-wise Heat/Sun Stroke deaths — **Odisha 2023 = 73** (58 M / 15 F); all-India 804, up 10.1% on 2022. Annual, state-level. |
| `Odisha.pdf` | **NFHS-5 (2020-21) fact sheets — Odisha state + all 30 districts**, ~187 pp. Real district-level demographic, housing, electricity and NCD indicators. |

### The defect that defines our approach

The existing notebook feeds **daily-max temperature together with daily-mean relative humidity** into a shade-WBGT approximation. Max temperature and max humidity do not co-occur — RH is at its daily *minimum* when T peaks. The consequence is visible in its own output:

- **9,084 of 18,265 days (~50%) are classified "Red (Severe/Extreme)"** across ten years.
- Max WBGT **50.0 °C** and max Heat Index **79.1 °C** — physically impossible (WBGT above ~35 °C is the human survivability limit).

An alert system that is red half the time is worse than no alert system: it guarantees alert fatigue and is indefensible in front of judges. **This is exactly why the hourly `nasapower_odisha` data must be the training base** — the correct method is to compute indices *hourly* (where T, RH, wind and radiation are physically consistent) and then aggregate the *index*, never the inputs.

That single correction is the scientific spine of this build, and it is the first thing we will demonstrate.

### Why the hourly grid unlocks the whole problem statement

The derived daily file has only `T2M_MAX, T2M_MIN, RH2M, WS10M, ALLSKY_SFC_SW_DWN`. The hourly grid additionally carries **`T2MDEW` (dewpoint)** and **`PS` (surface pressure)** — and that difference is decisive:

| Need | Daily file | Hourly grid |
| --- | --- | --- |
| Exact vapour pressure (no RH round-trip error) | ✗ | ✓ `T2MDEW` |
| **Liljegren WBGT** (needs barometric pressure) | ✗ | ✓ `PS` |
| **UTCI** (needs 10 m wind + hourly Tmrt) | ✗ | ✓ `WS10M` is already the exact height UTCI specifies |
| Physically consistent T/RH/wind/solar at the same instant | ✗ | ✓ |
| Night-time minimum of the *index* (22:00–06:00) | ✗ | ✓ |
| Degree-hours and consecutive-hours above threshold | ✗ | ✓ |
| Diurnal exposure profile for outdoor-worker risk windows | ✗ | ✓ |

The prior notebook declared UTCI infeasible because mean radiant temperature was unavailable. With hourly global horizontal irradiance plus solar geometry, Tmrt is derivable — so **UTCI, which the problem statement names explicitly, becomes tractable.**

### The second defect: there is no overlap between the mortality data and the weather data

Mortality runs **2007–2011**. The hourly weather grid runs **2015–2025**. **Zero overlapping days.** A heat→mortality exposure–response function therefore *cannot* be fitted from these two files, no matter how the joins are written. Any submission that claims to have "trained a mortality model on this data" has either not checked, or has leaked something.

Two further constraints compound it:

- **Density.** 49,259 exact-day deaths over 5 years ≈ **27 deaths/day statewide**, but only **~1.2 per district-day** across the 5 study districts. District-level *daily* count modelling is not statistically viable; statewide/pooled is.
- **Seasonality.** In the exact-day rows, deaths peak in **August (5,644) and December–January (~4,680)**, not in the April–June heat season. Part of this is genuine (monsoon infectious disease, winter cardiorespiratory), part is survey recall artefact, and the 47.6% missing-day rows are not missing at random. This must be stated, not smoothed over.

**The decided response** (your call, recorded here): use a **literature-transferred exposure–response curve** for heat and mortality in tropical South Asia, **calibrated to local baseline death rates estimated from the 2007–2011 AHS data**, and validated against the NCRB annual heat-stroke series. The DLNM machinery is still built — it fits the local seasonal/trend baseline, which *is* estimable without weather — and a `fit_local()` path is shipped so the transferred curve is replaced by a locally fitted one the moment paired data exists. Full detail in Phase 6.

**Consequence for the ML component:** the trainable supervised problem here is **forecasting thermal stress**, not forecasting deaths — and that is precisely what the mandated hourly dataset supports, with ~46 M labelled observations. See Phase 7.

### Two engineering gates that must be settled before any index is computed

These are the kind of silent-wrong-answer risks that sink a pipeline, so they were treated as explicit, testable checks rather than assumptions.

1. **Timestamp time-standard (UTC vs LST) — resolved during planning.** NASA POWER serves hourly data in UTC by default but supports `time-standard=LST`, and getting this wrong would silently corrupt every daily maximum, every night-minimum window and every alert by 5½ hours. Measured across three cells spanning the grid:

   | File | Peak irradiance hour | Peak T hour | Min T hour |
   | --- | --- | --- | --- |
   | `17.5_81.5_2015.csv` | 11 | 13 | 5 |
   | `20.0_85.0_2020.csv` | 12 | 13 | 5 |
   | `22.25_87.25_2025.csv` | 12 | 13 | 5 |

   Irradiance peaks at solar noon, temperature at ~13:00, minimum at ~05:00, and sunlit hours run 05–18. That is a textbook diurnal cycle in **Local Solar Time**. Under UTC the peak would sit at hour 06–07. **Confirmed: the data is LST, not UTC.** Ingest converts LST → IST using the cell's longitude offset from the 82.5°E standard meridian (up to ±20 min across the grid), and the ingest asserts the peak-irradiance-hour invariant on every cell so a future re-download in UTC fails loudly instead of quietly.

2. **Solar geometry and the beam/diffuse split.** `ALLSKY_SFC_SW_DWN` is global horizontal irradiance; Liljegren's globe-temperature solution needs the direct-beam fraction and the solar zenith angle. Use **`pvlib`** (`solarposition.get_solarposition` + the **Erbs** or **DISC** decomposition model) rather than hand-rolled astronomy — it is the validated standard and removes an entire class of bug.

### Scale note

~46 million hourly records is well past comfortable CSV territory. Ingest converts once to **partitioned Parquet with `float32` columns** (≈ 1.1 GB → roughly 250–400 MB compressed), after which the whole 11-year panel loads in seconds and index computation is a vectorised pass. Ingest is idempotent and incremental so it is never re-run by accident.

---

## Design principles

1. **Compute indices at native hourly resolution, aggregate afterwards.** `daily_max(WBGT(T_h, RH_h, WS_h, SW_h))` ≠ `WBGT(T_max, RH_mean, …)`.
2. **Relative, not absolute, thresholds.** Odisha's population is acclimatised. Epidemiology shows *anomaly relative to local climatology* predicts mortality better than absolute temperature. Thresholds come from per-ward, per-day-of-year percentiles of 2015–2025.
3. **Physically-grounded index implementations, unit-tested against published reference values.** Liljegren WBGT and the official UTCI polynomial, not one-line approximations.
4. **The epidemiology is a model, not a heuristic.** Exposure–response comes from a distributed-lag model fitted to real mortality counts, producing relative risk and attributable deaths — the language public-health officials actually use.
5. **Night matters.** Nocturnal heat (failure of overnight physiological recovery) is among the strongest mortality predictors and is absent from every temperature-threshold warning in use.
6. **Every number on the dashboard is explainable.** SHAP per ward, exposure–response curve per district, uncertainty band on every forecast.
7. **Degrade gracefully.** Live forecast API → cached forecast → climatological persistence. Demo works with no internet.

---

## Architecture

```
                    ┌────────────────────────────────────────────────────┐
  TRAINING          │ nasapower_odisha/ hourly 2015–2025 · 480 cells      │
  (offline)         │ mort_21_Odisha (2007–11) · AHS codebook · HVI       │
                    │ Odisha.pdf (NFHS-5) · NCRB ADSI                     │
                    └───────────────────────┬────────────────────────────┘
                                            ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ L1  INGEST     5,279 CSVs → Parquet panel, LST→IST, QC + provenance    │
   │ L2  INDICES    hourly WBGT(Liljegren) · UTCI · HI · Humidex · Tw · AT  │
   │ L3  AGGREGATE  daily max/mean · night-min 22–06 · degree-hours · spells│
   │ L4  CLIMATOLOGY per-cell day-of-year percentiles (p50/p90/p95/p98)·EHF │
   │ L5  DOWNSCALE  grid → ward (bilinear + UHI uplift from built-up frac.) │
   │ L6  HTSI       composite 0–100: intensity·anomaly·night·duration       │
   │ L7  BASELINE   AHS → expected deaths by district×age×doy   [FITTED]    │
   │     VULNER.    HVI remote sensing + NFHS-5 district sheets  [FITTED]    │
   │     RR CURVE   exposure–response on percentile scale    [TRANSFERRED]  │
   │ L8  MRI        baseline × (RR−1) × vulnerability × population          │
   │ L9  FORECAST   LightGBM on HTSI, D+1…D+5, quantile + conformal PI      │
   └────────────────────────────────────┬───────────────────────────────────┘
                                        ▼  artefacts/ (parquet + joblib)
   ┌────────────────────────────────────────────────────────────────────────┐
   │  FastAPI  /wards /htsi /mri /forecast /alerts /advisory /explain /cap   │
   │           /hap/trigger /optimize/cooling-centres /subscribe /webhook    │
   └──────┬──────────────────────────────────────────┬──────────────────────┘
          ▼                                          ▼
   React + MapLibre dashboard              Alert fan-out: SMS · WhatsApp ·
   (choropleth, D+0…D+5 slider,            CAP-XML (SACHET/NDMA) · webhook
    ward drill-down, SHAP, HAP console)
          ▲
   LIVE:  Open-Meteo / IMD hourly forecast ──► L2…L9 (same code path)
```

**Train on NASA POWER hourly reanalysis; serve on Open-Meteo/IMD hourly forecast — identical index and model code on both paths.** This is the single most important structural decision: it eliminates train/serve skew and makes the 3–5 day forecast real rather than a replayed historical slice.

---

## Repository layout

```
ushma/
├── README.md                    ← hero doc: problem, demo GIF, 60-second quickstart
├── pyproject.toml               ← installable package, pinned deps
├── Makefile / make.ps1          ← make data | make train | make serve | make test
├── docker-compose.yml
├── docs/                        ← see "Documentation" below
├── data/
│   ├── raw/                     ← existing files moved here (symlink/copy, originals untouched)
│   ├── interim/                 ← hourly tidy panel (parquet)
│   ├── processed/               ← ward-day features, climatology, model inputs
│   └── geo/                     ← ward shapefiles (USER-PROVIDED) + derived GeoJSON
├── artifacts/                   ← trained models, SHAP explainers, calibration curves
├── src/ushma/
│   ├── config.py                ← pydantic-settings; all paths/thresholds in one place
│   ├── ingest/   nasapower.py  openmeteo.py  imd.py
│   ├── indices/  wbgt_liljegren.py  utci.py  heat_index.py  humidex.py
│   │              wet_bulb.py  apparent_temp.py  aggregate.py  htsi.py
│   ├── climate/  climatology.py  anomaly.py  heatwave_spells.py
│   ├── geo/      grid_to_ward.py  uhi.py  ward_registry.py
│   ├── health/   mortality_etl.py  vulnerability.py  dlnm.py  mri.py
│   ├── forecast/ features.py  train.py  predict.py  uncertainty.py  backtest.py
│   ├── alerts/   thresholds.py  hap_state_machine.py  advisory.py  cap.py
│   │              i18n/{en,hi,or}.yaml  channels/{sms,whatsapp,webhook,console}.py
│   ├── optimize/ cooling_centres.py
│   └── explain/  shap_service.py
├── api/          main.py  routers/  schemas.py  deps.py
├── dashboard/    Vite + React + TypeScript + MapLibre GL + TanStack Query + Recharts
├── notebooks/    01_ingest_eda · 02_index_validation · 03_climatology ·
│                 04_mortality_dlnm · 05_forecast_model · 06_backtest_report
├── tests/        test_indices_reference.py  test_aggregation.py  test_dlnm.py
│                 test_alert_state_machine.py  test_api.py
└── scripts/      build_all.py  demo_replay.py  seed_demo_data.py
```

---

## Implementation plan

### Phase 0 — Foundation *(~1 h)*
- `pyproject.toml`, `src/ushma/config.py` (pydantic-settings), logging, `Makefile`/`make.ps1`.
- Missing dependencies to install: `matplotlib`, `plotly`, `statsmodels`, `lightgbm`, `xgboost`, `geopandas`, `shap`, `pyarrow`, `pvlib`, `pulp`, `httpx`, `pydantic-settings`, `pytest`, **`openpyxl`** (required to read the AHS codebook — without it the mortality file is undecodable) and **`pdfplumber`** (required for the NFHS-5 and NCRB extractions).
  *(Present already: pandas 2.3.3, numpy 2.2.6, scikit-learn 1.7.2, scipy, shapely, fastapi, uvicorn, torch, xarray, netCDF4.)*
- `data/raw/` population — **copy, never move**; original files stay where they are.

### Phase 1 — Hourly ingest *(`src/ushma/ingest/nasapower.py`)*
- Walk all 5,279 files; derive `lat`, `lon`, `year` from the filename and assign a stable `cell_id`; parse the `YYYYMMDDHH` index to a timestamp.
- **Resolve the time-standard gate above first**, then normalise everything to a single `ts_ist` column. Record the resolved standard in the dataset metadata so it can never be re-guessed downstream.
- Emit `data/interim/hourly_grid/` partitioned by `year`, schema `(cell_id, lat, lon, ts_ist, T2M, RH2M, T2MDEW, PS, WS10M, ALLSKY_SFC_SW_DWN)` in `float32`.
- **QC report artefact**: expected 8,760 rows (8,784 in 2016/2020/2024) per cell-year, actual counts, gap runs, physical-range violations (RH ∉ [0,100], T2MDEW > T2M, negative irradiance, night-time irradiance > 0), and a `-999`/sentinel sweep even though the sample showed none.
- **Handle the single missing file `20.0_83.5_2024.csv`** explicitly — fill by inverse-distance interpolation from its four neighbours, flagged `is_interpolated=True` in a provenance column rather than silently imputed.
- Clip the 480-cell rectangle to Odisha's actual boundary; cells outside the state are retained but marked, since the western column (lon 81.5) sits on the Chhattisgarh side and the southern row (lat 17.5) on the Andhra side.
- **Grid spacing is 0.25° ≈ 27 km** — coarser than a municipal ward. This is exactly why Phase 4's downscaling and UHI uplift are a documented modelling layer with stated uncertainty, not a cosmetic reprojection. Being upfront about this is a strength; pretending 27 km data is ward-resolved is the mistake judges look for.

### Phase 2 — Thermal index engine *(`src/ushma/indices/`)* — **the scientific core**
All vectorised NumPy, all operating on the hourly panel.

| Module | Method | Why |
| --- | --- | --- |
| `wbgt_liljegren.py` | **Liljegren et al. (2008)** iterative solution for natural wet-bulb and globe temperature from T, RH, wind, direct/diffuse solar and solar zenith angle | The NIOSH/US-military reference implementation. Uses *exactly* the variables POWER hourly provides. Replaces the one-line BOM shade approximation. |
| `utci.py` | Official **Bröde et al. (2012)** 6th-order polynomial + Tmrt estimated from globe temperature (ISO 7726) | The PS names UTCI explicitly. Prior notebook declared it impossible; hourly solar radiation makes it tractable. |
| `heat_index.py` | NWS **Rothfusz** regression + both NOAA adjustments | Reuse the existing correct implementation from `thermal_stress_index.ipynb` cell 6, ported and tested. |
| `humidex.py` | Environment Canada | Widely understood public-facing number. |
| `wet_bulb.py` | **Stull (2011)** empirical Tw | Enables the 35 °C survivability-limit narrative. |
| `apparent_temp.py` | BOM AT | Port from notebook cell 10. |
| `aggregate.py` | daily max / mean / **night-min (22:00–06:00 IST)** / **degree-hours above threshold** / consecutive-hours-above | Duration and night-time relief are what kill; peak alone is not. |

Two shared helpers the whole engine depends on:
- `psychro.py` — vapour pressure computed from **`T2MDEW` directly** (Buck equation) rather than round-tripping through RH, which is both more accurate and lets us cross-check the supplied `RH2M` as a QC signal.
- `wind.py` — logarithmic wind profile converting `WS10M` → 2 m wind for WBGT, with a floor at 0.13 m/s (Liljegren's stated lower bound; unbounded low wind makes the globe-temperature solver diverge). UTCI consumes `WS10M` unconverted, which is the height it is defined at, and is clamped to its published validity domain of 0.5–17 m/s.

**Validation (`tests/test_indices_reference.py`):** assert each implementation reproduces published reference values — Liljegren's tabulated test cases, the official UTCI reference table, NOAA's HI chart. A passing test suite on physical constants is the single most convincing artefact we can put in front of a science-literate judge.

### Phase 3 — Climatology & heatwave characterisation *(`src/ushma/climate/`)*
- Per grid cell, per day-of-year (±15-day window), percentiles p50/p90/p95/p98 of daily-max WBGT/UTCI/HTSI over 2015–2025.
- **Excess Heat Factor (EHF)** — the Australian BOM operational metric combining *significance* (3-day mean vs 95th percentile) and *acclimatisation* (3-day mean vs trailing 30-day mean). Empirically the best-validated single predictor of heat mortality anywhere in the world; almost no Indian system uses it.
- Spell detection: onset, duration, peak, cumulative exposure.

#### The Human Thermal Stress Index (HTSI) — concrete definition

The PS asks for *"a comprehensive Human Thermal Stress Index (integrating temperature, humidity, wind, and radiation)"*. A single named index (WBGT alone, UTCI alone) does not satisfy "comprehensive", and an undefined blend is not defensible. HTSI is therefore a **0–100 composite of four physiologically distinct stress channels**, each already validated in the literature:

| Component | Weight | Measures | Source |
| --- | --- | --- | --- |
| **Intensity** | 0.40 | Daily-max UTCI mapped onto its published thermal-stress bands, cross-checked against Liljegren WBGT | Peak physiological load |
| **Anomaly** | 0.25 | Percentile of today's value within this cell's day-of-year climatology (±15 d window, 2015–2025) | Acclimatisation — the same 42 °C is not the same risk in Bolangir and Balasore |
| **Night relief deficit** | 0.20 | Shortfall of the 22:00–06:00 index minimum below the recovery threshold | Failure of overnight physiological recovery; the strongest under-used mortality predictor |
| **Duration** | 0.15 | Consecutive days above the p90 threshold, saturating (diminishing marginal effect after ~5 days) | Cumulative strain and depletion of coping capacity |

Reported alongside as a separate operational number: **Excess Heat Factor (EHF)** — the Australian BOM metric combining 3-day significance against the 95th percentile with acclimatisation against the trailing 30-day mean. It is the best externally validated heat-mortality predictor in operational use anywhere, and essentially unused in Indian warning systems.

Weights live in `config.py`, not in code. `docs/04_HTSI_SPEC.md` carries a **sensitivity analysis** showing how alert counts and mortality-correlation change as weights vary — because the first question a serious judge asks about any composite index is "where did those weights come from?", and the right answer is a table, not a shrug. The weights are additionally *tuned* against observed mortality (maximising DLNM fit) and the tuned-vs-prior comparison is reported.

### Phase 4 — Ward downscaling *(`src/ushma/geo/`)*
**You are providing ward shapefiles.** The code is written to consume them, with a clean contract:

- Expected input: `data/geo/wards.geojson` (or `.shp`), EPSG:4326, with at minimum `ward_id`, `ward_name`, `ulb_name`, `district`. Optional and used when present: `population`, `area_sqkm`, `elderly_pct`, `slum_pop_pct`, `built_up_frac`, `ndvi`.
- `ward_registry.py` validates the schema, reports missing optional fields, computes centroids and area, and **fails loudly with a precise message** rather than silently guessing.
- `grid_to_ward.py`: bilinear interpolation from the POWER grid to ward centroid, plus area-weighted grid-cell overlay for large wards.
- `uhi.py`: urban-heat-island uplift ΔT = f(built-up fraction, population density, NDVI), calibrated to published Indian city UHI magnitudes (typically +1.5 to +4 °C nocturnal). Documented as a parameterisation with a clean seam for real MODIS/Landsat LST later.
- **Until the shapefiles land**, a `--synthetic-wards` flag generates a ward registry from district polygons so the whole pipeline, API and dashboard are developable and demo-able on day one. Clearly labelled as synthetic in both the data and the UI.
- District-name normalisation utility — `constraints.ipynb` writes `BALANGIR`, the thermal notebook uses `Bolangir`, `Khordha_Bhubaneswar`. A canonical `district_key` mapping (with LGD codes) prevents silent join failures.

### Phase 5 — Health data & vulnerability *(`src/ushma/health/`)*

**Scope decision: all 30 Odisha districts**, with the 5 original study districts kept as the deep-dive demo narrative.

- `ahs_codebook.py`: parse `Data_structure_AHS.xlsx` (7 sheets) into machine-readable code→label maps. **Read it with `openpyxl`** (not currently installed) — the mortality file is 122 columns of bare integers and is unreadable without this decoder. The `State District Codes` sheet gives the authoritative district 1–30 mapping.
- `mortality_etl.py`: read the **pipe-delimited** file, decode codes, unify the three split age columns (`age_of_death_below_one_month` in days / `age_of_death_below_eleven_month` in months / `age_of_death_above_one_year` in years) into one `age_years`, and build:
  - a **daily** statewide series from the 49,259 exact-day rows, and
  - a **monthly** district series from all 94,619 rows (day not required),
  with survey weights `wt` applied and both an unweighted and weighted variant retained.
  - **Guard against the trap:** `sex`, `age`, and all asset columns in the household block describe the **head of household**, not the deceased. Only `deceased_sex` and the three age-of-death columns describe the decedent. The codebook states this explicitly; it is an easy and invisible mistake.
  - Missing-day rows are **not** dropped silently. They are redistributed within their month proportionally to the observed within-month day distribution, and a sensitivity analysis compares exact-day-only vs redistributed results.
- **Baseline / expected deaths** via quasi-Poisson GLM with natural splines on day-of-year (seasonality), a long-term time trend, and day-of-week — per district and per age band (0–4, 5–14, 15–44, 45–64, **65+**, which is 53.8% of deaths). This is fully estimable from 2007–2011 alone, without any weather, and it is the *local* half of the risk model.
- `nfhs_etl.py`: **extract the 30 district fact sheets from `Odisha.pdf`** (NFHS-5 2020-21) — elderly share, household electricity, improved housing, cooking fuel, drinking-water source, anaemia, hypertension and diabetes prevalence, health-insurance coverage. `pdfplumber` for text/tables, with a hand-verified mapping and a spot-check test against the printed state sheet. This replaces the four flat national-fallback columns in the HVI file with genuine district-level variation.
- `vulnerability.py`: rebuild the composite Heat Vulnerability Index on the standard three-pillar structure —
  - **Exposure**: HVI remote-sensing columns (`lst_day_mean`, `lst_afternoon_mean`, `built_surface_mean`, `viirs_ntl_mean`, `urban_lc_fraction`) — these *do* vary across Odisha and are kept.
  - **Sensitivity**: NFHS-5 elderly/child share, NCD prevalence, anaemia; AHS-derived chronic-illness and disability rates; outdoor-worker proxy from occupation codes.
  - **Adaptive capacity**: NFHS-5 electricity access, housing type, water source; HVI `healthcare_travel_min`, `green_fraction`, `ndvi_mean`.
  Min–max normalised, **weights in config**, with an **equal-weight / expert-weight / PCA** comparison reported side by side so the choice is visible rather than asserted.
- `crosswalk.py`: **one canonical district key.** Three incompatible schemes are in play — AHS codes 1–30, HVI `dist_code` 370–399 (string, some alphanumeric elsewhere), and weather strings like `Khordha_Bhubaneswar`. Spellings diverge too (`KEONJHAR (KENDUJHAR)`/`KENDUJHAR`, `NUAPARHA`/`NUAPADA`, `BALASORE`/`BALESHWAR`, `SUBARNAPUR`/`SONAPUR`, `BALANGIR`/`Bolangir`). A single reviewed crosswalk table with LGD codes, plus a test asserting **every** join key resolves and no row is dropped. Silent join failure is the most common way a pipeline like this produces confident nonsense.

### Phase 6 — Mortality Risk Index *(`src/ushma/health/dlnm.py`, `exposure_response.py`, `mri.py`)*

Given no paired weather–mortality period, the risk model is **explicitly two-part**, and the boundary between "learned from your data" and "transferred from literature" is drawn in the open:

| Component | Source | Fitted here? |
| --- | --- | --- |
| Baseline / expected deaths by district, age, day-of-year, trend | AHS 2007–2011 | ✅ Fitted locally |
| Population and age structure | NFHS-5 + Census projections | ✅ Local |
| Vulnerability multiplier | HVI remote sensing + NFHS-5 | ✅ Local |
| **Heat exposure–response RR(exposure, lag)** | Published tropical-South-Asia heat–mortality literature | ⚠️ **Transferred**, in a cited YAML, swappable |

- `dlnm.py` implements the full **Distributed Lag Non-Linear Model** machinery — natural-cubic-spline cross-basis in exposure ⊗ lag (0–10 days), quasi-Poisson GLM via `statsmodels`. It is used *now* to fit the baseline, and exposes `fit_local(exposure, deaths)` which becomes live the day a paired dataset exists. No maintained Python equivalent of R's `dlnm` exists; building one is itself a contribution.
- `exposure_response.py` loads the transferred RR surface from `config/exposure_response.yaml` — parameterised on **exposure percentile** rather than absolute °C, which is what makes transfer between climates legitimate. Every parameter carries its citation inline. Minimum-mortality percentile, RR at p95/p99, and lag structure are all explicit, editable numbers.
- `mri.py` composes:
  `excess_deaths(ward, day) = baseline_rate(district, doy, age) × [RR(HTSI_pct, lag) − 1] × vulnerability_mult(ward) × population(ward, age)`
  reported as **expected excess deaths and excess ED attendances with uncertainty intervals**, plus attributable fraction and attributable number — the vocabulary health departments actually use — and a 0–100 MRI for the map colour ramp.
- **Validation** (`docs/11`):
  1. **NCRB anchor** — aggregate predicted heat-attributable deaths to Odisha-year and compare against the ADSI series (2023 = 73 heat/sunstroke deaths). Police-reported heat deaths are a severe undercount of true heat-attributable mortality, so the test is **order-of-magnitude plausibility and year-to-year direction**, not equality. Stated as such.
  2. **Seasonal-shape check** — does the model's predicted excess line up with any April–June signal in the AHS data? Current evidence says the raw all-cause peak is in **August and December–January**, so this check is expected to be weak. We report that honestly, and explain why (monsoon infectious disease, winter cardiorespiratory, survey recall bias, 47.6% imputed days).
  3. **Sensitivity** — MRI recomputed across the plausible RR range so the reader sees how much of the output rides on the transferred parameter.

### Phase 7 — Forecast models *(`src/ushma/forecast/`)*

**The honest framing, and the one the data supports:** with no paired weather–mortality period, *deaths* are not a trainable label. *Thermal stress* is — with ~46 M labelled hourly observations across 480 cells and 11 years, all from the mandated `nasapower_odisha` dataset. So the pipeline splits cleanly into a **learned** stage and a **deterministic** stage:

```
   ML (supervised, trained on nasapower_odisha)      Epidemiological (transparent)
   ───────────────────────────────────────────      ─────────────────────────────
   history ──► HTSI forecast D+1 … D+5  ────────►   RR × baseline × vulnerability
              + prediction intervals                 ──► excess deaths / MRI
```

**Model 1 — HTSI / thermal-stress forecaster** *(this is the trained model)*
- Target: ward/cell daily-max UTCI, WBGT, night-min and composite HTSI at horizons D+1…D+5 (one model per horizon — direct multi-horizon, no recursive error accumulation).
- Features: lagged index values (1–14 d), rolling means/maxima, EHF, day-of-year climatology and anomaly percentile, spell-day counter, night-min history, harmonic calendar terms, cell latitude/longitude/elevation, and — on the live path — NWP forecast fields.
- LightGBM primary, XGBoost comparator, **seasonal-naive and climatology as mandatory baselines**.
- **Split: train 2015–2022, validate 2023, test 2024–2025.** Strictly temporal; never random K-fold on a time series.
- **Uncertainty**: LightGBM quantile objective (τ = 0.1/0.5/0.9) plus **split-conformal** calibration so stated coverage is actual coverage. Every forecast on the dashboard carries a band, never a bare point.
- **Live path**: when Open-Meteo/IMD NWP is reachable, the model runs as a **statistical downscaling and bias-correction layer** on top of NWP — learning the ward-level residual structure (UHI, coastal effects) that a 27 km grid cannot resolve. That is a genuinely useful role for an ML model here, rather than a decorative one.

**Model 2 — risk transform**: deterministic, from Phase 6. No training, fully inspectable, every term traceable.

**The headline evaluation — and the entire thesis of the problem statement:**
> Does an impact-based index beat a temperature threshold at identifying dangerous days?

Measured explicitly by comparing alert sets generated by (a) IMD-style absolute Tmax thresholds, (b) daily-max-T + daily-mean-RH WBGT — *the existing notebook's method* — and (c) our hourly HTSI, against high-physiological-risk days defined by UTCI/WBGT exceedance. Reported as ROC-AUC, precision/recall, Brier score, reliability curves, CRPS, and a lead-time-vs-skill curve. **The alert rate comparison alone is the story**: the existing method fires Red on ~50% of all days; a correctly computed, percentile-anchored index should fire on roughly 2–8% of summer days. That single before/after number belongs on a slide.

### Phase 8 — Explainability *(`src/ushma/explain/`)*
Explanation runs on **both** stages, which is only possible because they were kept separate:
- **Forecast stage** — SHAP TreeExplainer over the LightGBM HTSI models; per-ward, per-day waterfall served through `/explain/{ward_id}`.
- **Risk stage** — needs no SHAP: it is a product of named terms, so the dashboard decomposes it arithmetically (baseline × RR × vulnerability × population), which is *more* interpretable than any attribution method.
- Rendered as plain language: *"Tomorrow's risk in Ward 12 is driven by the 4th consecutive day above the 95th percentile (+18 pts), an overnight minimum that fails to fall below 28 °C (+12 pts), and a 22% elderly population (×1.4 on baseline risk)."*
- Global SHAP summaries and the exposure–response curve go in the validation report.

### Phase 9 — Alerting & Heat Action Plan *(`src/ushma/alerts/`)*
- **Threshold engine**: combined absolute (WBGT/UTCI physiological bands) **and** relative (percentile anomaly) criteria, so alerts fire on what is unusual *here*, not on a national number.
- **HAP state machine** aligned to NDMA guidance: `NORMAL → WATCH(Yellow) → WARNING(Orange) → EMERGENCY(Red)`, with **hysteresis and minimum dwell time** so alerts cannot flap day to day. Every transition emits an auditable event with the reason and the evidence.
- **Advisory generator**: audience-targeted templates — general public, elderly/chronically ill, outdoor workers, schools, hospitals (surge prep), power utility (load forecast), municipal ops (cooling centres, water tankers) — each mapped to the NDMA HAP action catalogue.
- **Trilingual**: Odia (ଓଡ଼ିଆ), Hindi, English, in YAML so translations are reviewable, not hardcoded.
- **CAP 1.2 XML output** — the Common Alerting Protocol standard that India's SACHET/NDMA platform consumes. Producing valid CAP means the system can plug into national infrastructure on day one; almost no hackathon entry does this.
- **Channels** behind one interface: console (demo), webhook, SMS, WhatsApp (Twilio/Gupshup adapters). Ship with a **simulated provider by default** — no credentials, no cost, fully demo-able — with the real adapter one config flag away.
- **Subscription model**: officials subscribe by ward/role; delivery log, dedupe, and rate limiting.

### Phase 10 — Cooling-centre siting optimiser *(`src/ushma/optimize/`)*
- Maximal-covering location problem over ward centroids weighted by `population × vulnerability × forecast MRI`, solved with PuLP (exact) and a greedy fallback.
- Answers the question a commissioner actually asks: *"I can open 12 cooling centres. Where?"*
- **Counterfactual panel**: projected reduction in excess deaths for a chosen intervention set (cooling centres, work-hour shift, school closure) — turns a forecast into a decision.

### Phase 11 — API *(`api/`)*
FastAPI, fully typed, auto-generated OpenAPI docs, API-key auth on write/trigger routes, rate limiting.

| Route | Purpose |
| --- | --- |
| `GET /v1/wards` · `/wards/{id}` | Registry + geometry + vulnerability profile |
| `GET /v1/htsi?ward&from&to` | Thermal stress index time series (hist + forecast) |
| `GET /v1/mri?ward&horizon` | Mortality risk index, excess deaths, intervals |
| `GET /v1/forecast/{ward_id}` | D+0…D+5, all indices, prediction bands |
| `GET /v1/alerts/active` · `POST /v1/alerts/evaluate` | Current alert state; force re-evaluation |
| `GET /v1/advisory/{ward_id}?lang=or\|hi\|en&audience=` | Rendered advisory text |
| `GET /v1/alerts/{id}/cap.xml` | CAP 1.2 alert document |
| `POST /v1/hap/trigger` | Emit HAP action set; logged and auditable |
| `POST /v1/optimize/cooling-centres` | Siting recommendation |
| `GET /v1/explain/{ward_id}` | SHAP attribution |
| `POST /v1/subscribe` · `/webhooks` | Channel registration |
| `GET /v1/health` · `/v1/model-card` | Liveness + machine-readable model metadata |
| `WS /v1/stream/alerts` | Live alert push to the dashboard |

### Phase 12 — Dashboard *(`dashboard/`)*
Vite + React + TypeScript + MapLibre GL + TanStack Query + Recharts + Tailwind.

- **Map**: ward choropleth, layer switch (HTSI / MRI / vulnerability / excess deaths), D+0→D+5 time slider with animated play, cooling-centre and hospital pins.
- **Ward drill-down**: index time series with forecast band, SHAP waterfall in plain language, demographic profile, recommended actions, one-click "send advisory".
- **Command console**: ranked alert table, HAP state per ULB, action checklist with acknowledgement, delivery log.
- **Validation tab**: live model-performance charts — the skill-vs-temperature-threshold comparison front and centre.
- **Accessibility & polish**: colour-blind-safe sequential ramp (not naive red-green), dark mode, keyboard navigation, `prefers-reduced-motion` respected, mobile-responsive.
- **Low-bandwidth ASHA/field view**: a stripped route (`/field`) — one ward, today's band, three actions, installable PWA with offline cache. The last-mile worker is the actual user of this system and is usually forgotten.

### Phase 13 — Demo reliability
- `scripts/demo_replay.py`: replays a real historical Odisha heatwave hour-by-hour as if live, so the demo is deterministic and works with no internet.
- Seeded fixtures; `make demo` brings up API + dashboard with data already built.
- `docs/14_DEMO_SCRIPT.md`: a timed 5-minute walkthrough with the exact narrative beats.

---

---

## Build order

Sequenced so something works end-to-end early and every later phase slots into a running system rather than a big-bang integration at the end.

| Milestone | Phases | You can see |
| --- | --- | --- |
| **M1 — Data spine** | 0, 1 | Parquet panel built, QC report, LST guard passing. The 2 GB of CSVs become a queryable dataset. |
| **M2 — Science core** | 2, 3 | Hourly UTCI/WBGT/HI with a green test suite, and the **before/after alert-rate chart that kills the 50%-Red problem**. This is the first demo-able artefact and the strongest one. |
| **M3 — Places** | 4, 5 | 30 districts joined cleanly across all four sources, NFHS-5 vulnerability, synthetic wards live |
| **M4 — Risk** | 6 | MRI with excess-death estimates and the NCRB sanity check |
| **M5 — Forecast** | 7, 8 | D+1…D+5 with intervals, backtest report, SHAP |
| **M6 — Product** | 9, 11, 12 | Alerts, API, dashboard — the thing judges actually look at |
| **M7 — Edge** | 10, 13 | Cooling-centre optimiser, counterfactuals, field PWA, demo replay |

Docs are written *alongside* their phase, not retrofitted at the end — a doc written after the fact describes what you wish you'd built.

---

## Documentation *(the `.md` deliverables)*

| File | Contents |
| --- | --- |
| `README.md` | Problem, solution, architecture diagram, screenshots, 60-second quickstart, feature matrix |
| `docs/00_PROBLEM_AND_APPROACH.md` | PS decomposition → requirement traceability matrix → how each requirement is met |
| `docs/01_ARCHITECTURE.md` | Layer diagram, data flow, train/serve parity, technology choices and rejected alternatives |
| `docs/02_DATA_DICTIONARY.md` | Every source, every column, units, provenance, licence, known quality issues |
| `docs/03_THERMAL_INDICES.md` | Full derivations, constants, citations, validation table vs published reference values |
| `docs/04_HTSI_SPEC.md` | Composite index definition, component weights, sensitivity analysis, banding rationale |
| `docs/05_MORTALITY_RISK_MODEL.md` | DLNM formulation, exposure–response curves, MRI composition, assumptions |
| `docs/06_WARD_DOWNSCALING.md` | Shapefile contract, interpolation method, UHI parameterisation, uncertainty |
| `docs/07_API_REFERENCE.md` | Endpoints, schemas, auth, rate limits, curl examples, CAP sample |
| `docs/08_DASHBOARD.md` | Screen-by-screen guide, colour semantics, accessibility statement |
| `docs/09_ALERTING_AND_HAP.md` | Threshold logic, state machine, NDMA HAP mapping, advisory catalogue, escalation matrix |
| `docs/10_MODEL_CARD.md` | Intended use, out-of-scope use, training data, performance by subgroup, fairness, failure modes |
| `docs/11_VALIDATION_REPORT.md` | Backtest results, skill vs baselines, calibration, the temperature-only comparison |
| `docs/12_DEPLOYMENT.md` | Local, Docker, cloud; scaling; cost estimate for state-wide rollout |
| `docs/13_LIMITATIONS_AND_ETHICS.md` | Honest limits, privacy of mortality microdata, equity of alert distribution, misuse risks |
| `docs/14_DEMO_SCRIPT.md` | Timed judge walkthrough |
| `docs/15_ROADMAP.md` | Path from prototype to state deployment; IMD/SACHET integration; satellite LST |

Every doc written as a real engineering document — no filler, diagrams where a diagram is clearer than prose, citations where a claim needs one.

---

## What makes this win

1. **Two real defects found in the supplied material, and fixed in the open.** The 50%-Red-days / 50 °C-WBGT input-pairing error, and the fact that the mortality and weather data do not overlap by a single day. Both shown with evidence, both addressed. Most teams will join those files and never notice; the ones who do notice usually hide it. Leading with the audit is the strongest opening a technical presentation can have.
2. **The time-standard was verified, not assumed** — measured, tabulated, and asserted in the ingest so it can never silently regress.
3. **UTCI actually computed**, which the prior analysis declared infeasible; made tractable by the hourly data's irradiance plus `PS` and `T2MDEW`.
4. **Unit tests asserting physical correctness** against published reference tables for Liljegren WBGT, UTCI and NWS Heat Index.
5. **A real epidemiological structure** — DLNM, relative risk, attributable fraction — with the learned/transferred boundary drawn explicitly rather than a black box labelled "AI".
6. **An explicit, measured comparison against the temperature-threshold status quo** — the literal thesis of the problem statement, quantified, with the alert-rate before/after as the headline number.
7. **CAP 1.2 output** — plugs into India's SACHET/NDMA alerting infrastructure on day one.
8. **Night-time heat and the Excess Heat Factor** — operationally validated mortality predictors, essentially unused in Indian warning systems.
9. **Vulnerability built on real district variation** — NFHS-5 extracted from the supplied PDF, replacing four HVI columns that are identical for all 30 districts and therefore carry no information.
10. **Decisions, not just dashboards** — cooling-centre siting optimiser and a counterfactual "lives saved" panel.
11. **The last mile** — Odia advisories and an offline PWA field view for ASHA workers.
12. **Honesty as a feature** — a model card and a limitations document. Judges ask what's wrong with it; we hand them the page before they ask.

---

## Verification

| Layer | How we prove it works |
| --- | --- |
| Indices | `pytest tests/test_indices_reference.py` — Liljegren, UTCI, HI reproduce published values within tolerance |
| Aggregation | Property tests: daily-max-of-hourly ≥ index-of-daily-max; night-min window correct across the LST→IST conversion |
| Ingest | 8,760/8,784 rows per cell-year; **peak-irradiance-hour ≈ 12 asserted on every cell** (the LST guard); QC report artefact; the one missing 2024 file flagged as interpolated, never silently filled |
| Crosswalk | Every district key in all four sources resolves; **zero rows dropped on any join** — asserted, not assumed |
| Mortality ETL | Decoded counts reconcile to the raw 94,619; exact-day subset = 49,259; `deceased_sex` never confused with household-head `sex` |
| Climatology | Percentile monotonicity; alert rate on historical data lands in a plausible 2–8% of summer days (vs the current 50%) |
| Downscaling | Ward-mean reconciles with parent grid cell within tolerance; shapefile contract validation test |
| Risk model | Exposure–response is U-shaped with a plausible minimum-mortality percentile; RR at p99 within the literature range (~1.1–1.5); predicted Odisha heat deaths within order of magnitude of the NCRB series |
| Forecast | `notebooks/06_backtest_report` → skill vs persistence/climatology/temperature-threshold; calibration curves; conformal coverage ≈ nominal |
| Alerts | State-machine unit tests incl. hysteresis and flapping; CAP XML validates against the CAP 1.2 schema |
| API | `pytest tests/test_api.py` with FastAPI TestClient; OpenAPI schema snapshot |
| Dashboard | Playwright smoke test: load → select ward → slide to D+5 → advisory renders in Odia |
| End-to-end | `make demo` → `scripts/demo_replay.py` replays a historical heatwave; alerts escalate and de-escalate as they should |

---

## Decisions recorded

| Question | Decision |
| --- | --- |
| Deliverable | Full end-to-end stack — pipeline, indices, models, API, GIS dashboard, alerting |
| Stack | Python + FastAPI backend, React + MapLibre/Leaflet dashboard |
| Ward granularity | **You supply the shapefiles**; code written to the contract in Phase 4, `--synthetic-wards` until they land |
| Mortality/weather gap | Literature-transferred exposure–response, locally calibrated baseline (no external download) |
| Coverage | **All 30 Odisha districts**, 5 study districts as the deep-dive demo |
| Vulnerability | Extract NFHS-5 district fact sheets from `Odisha.pdf` |
| External validation | NCRB ADSI annual heat-stroke series |
| Extras | All of them — explainability, validation rigour, and the ops/impact layer |

## Known limitations, stated upfront

These go in `docs/13_LIMITATIONS_AND_ETHICS.md` and on a slide. Naming them first is how we keep control of the questions we get asked.

1. **The heat exposure–response is transferred, not locally fitted** — because the supplied data makes local fitting impossible. The `fit_local()` path is built and documented; it needs a paired weather–mortality period.
2. **Mortality data is 2007–2011 survey data**, weighted, with no heat cause code and 47.6% imputed days. It calibrates baselines; it does not validate heat effects.
3. **The weather grid is 0.25° ≈ 27 km.** Ward-level output is a documented downscaling with stated uncertainty, not a measurement.
4. **The UHI uplift is a parameterisation**, calibrated to published Indian city magnitudes, pending real satellite LST.
5. **The raw all-cause seasonal peak is August and December–January, not April–June** — reported as found, with the likely reasons.
6. **Mortality microdata is sensitive.** Names are already stripped; we keep it out of the repo, out of the API, and out of any artefact above district-month aggregation.

## What I need from you

- **Ward shapefiles** at `data/geo/wards.geojson` (or `.shp` + sidecars), EPSG:4326, with `ward_id`, `ward_name`, `ulb_name`, `district` at minimum. Everything is developable and demo-able without them via `--synthetic-wards`, so this is not a blocker — but the sooner they land, the sooner the map is real.