# Data Dictionary

Every source, what is actually in it, and what it can and cannot support. Written from direct inspection of the files, not from their filenames.

---

## Summary of what the supplied data can and cannot do

| Question | Answerable? | Why |
| --- | --- | --- |
| What is the hourly thermal stress across Odisha, 2015–2025? | **Yes** | 480-cell hourly grid with all four governing variables |
| How unusual is today relative to local climate? | **Yes** | 11 years is enough for a day-of-year percentile climatology |
| What is the baseline death rate by district, age and season? | **Yes** | AHS mortality microdata, 2007–2011 |
| Which districts are most vulnerable? | **Yes** | HVI remote sensing + NFHS-5 district fact sheets |
| **How much does heat raise mortality *in Odisha*?** | **No** | **Mortality is 2007–2011; weather is 2015–2025. Zero overlapping days.** |
| Which grid cells are in which district? | **Approximately** | No boundary polygons supplied; size-weighted centroid assignment, 234 in-state cells (see `06_WARD_DOWNSCALING.md`) |

The fifth row is the defining constraint of this project. See §3.5 and `05_MORTALITY_RISK_MODEL.md`.

---

## 1. `nasapower_odisha/` — hourly weather grid ★ primary training source

| Property | Value |
| --- | --- |
| Files | **5,279** CSVs, ~2.0 GB |
| Naming | `{lat}_{lon}_{year}.csv` |
| Grid | **480 points**, complete 0.25° lattice |
| Extent | lat 17.50–22.25 °N × lon 81.50–87.25 °E (20 × 24) |
| Years | 2015–2025 (11) |
| Resolution | **Hourly** |
| Rows | 8,760/year (8,784 in 2016, 2020, 2024) — **~46.2 million total** |
| Index | `YYYYMMDDHH`, **interval-start label** |
| Time standard | **Local Solar Time** (measured, see `03_THERMAL_INDICES.md` §3) |
| Header | Byte-identical across all 5,279 files; no `-BEGIN HEADER-` preamble |
| Fill values | No `-999` found |
| Missing | **1 file**: `20.0_83.5_2024.csv` |

### Columns

| Column | Units | Description | Used for |
| --- | --- | --- | --- |
| *(index)* | — | `YYYYMMDDHH` local solar time | Timestamp |
| `T2M` | °C | Air temperature at 2 m | All indices |
| `RH2M` | % | Relative humidity at 2 m | QC cross-check only — we derive RH from dewpoint |
| `T2MDEW` | °C | Dewpoint at 2 m | **Vapour pressure** (more direct than RH) |
| `PS` | kPa | Surface pressure | Liljegren WBGT, air density |
| `WS10M` | m/s | Wind speed at 10 m | UTCI (native height); converted to 2 m for WBGT |
| `ALLSKY_SFC_SW_DWN` | W/m² | Global horizontal irradiance | Radiant load, beam/diffuse split |

### Why this file and not the derived daily one

The derived `master_weather_odisha.csv` lacks **`T2MDEW`** and **`PS`**, and that difference is decisive:

| Requirement | Daily file | Hourly grid |
| --- | --- | --- |
| Liljegren WBGT (needs barometric pressure) | ✗ | ✓ |
| UTCI (needs 10 m wind + hourly Tmrt) | ✗ | ✓ |
| Physically consistent T/RH/wind/solar at one instant | ✗ | ✓ |
| Night-time minimum of the *index* | ✗ | ✓ |
| Degree-hours, consecutive-hours above threshold | ✗ | ✓ |

### Known quality issues

| Issue | Magnitude | Handling |
| --- | --- | --- |
| `T2MDEW > T2M` | 0.60% of rows; `RH2M` exactly 100.0 on all of them; median excess 0.40 °C; clusters 00–06 IST | Dewpoint clamped to air temperature in `vapour_pressure`; count reported in QC |
| Missing cell-year | `20.0_83.5_2024.csv` | Inverse-distance interpolation from 4 neighbours, flagged `is_interpolated=True` |
| Grid extends beyond Odisha | Western column (81.5 °E) is Chhattisgarh; southern row (17.5 °N) is Andhra Pradesh | Retained but marked; clipped to state boundary downstream |
| Resolution vs. wards | 0.25° ≈ **27 km**, coarser than any municipal ward | Explicit downscaling layer with stated uncertainty |

### Derived output → `data/interim/hourly_grid/year=YYYY/part.parquet`

| Column | Type | Note |
| --- | --- | --- |
| `cell_id` | int16 | Stable, ordered SW→NE |
| `lat`, `lon` | float32 | Grid centre |
| `ts_utc` | datetime64 | Derived: stamp − measured offset |
| `ts_ist` | datetime64 | `ts_utc` + 5:30. Lands on the half-hour — **not** resampled, since inventing on-the-hour IST values would fabricate precision |
| `T2M … ALLSKY_SFC_SW_DWN` | float32 | As supplied |
| `is_interpolated` | bool | Provenance flag |

**2.0 GB CSV → 351 MB Parquet** (5.7× compression), 46.2 M rows.

> **Partition edge note.** Partitions are keyed on the *file* year, so a UTC+6 cell's 2024 partition begins at 2023-12-31 23:30 IST. Daily aggregation must load adjacent years to avoid truncating the first and last day.

---

## 2. Derived files already in the folder

### `master_weather_odisha.csv`
18,265 rows = 5 districts × 3,653 days (2015-01-01 → 2024-12-31). Columns `YEAR, DOY, T2M_MAX, T2M_MIN, RH2M, WS10M, ALLSKY_SFC_SW_DWN, district`. Districts: `Khordha_Bhubaneswar, Balasore, Sambalpur, Bolangir, Sundargarh`.

### `master_weather_odisha_thermal.csv`
Same 18,265 rows plus `HI_C, WBGT, AT_C, WBGT_Risk`. **No UTCI.**

`WBGT_Risk` distribution — the symptom that motivated the rebuild:

| Band | Days | Share |
| --- | --- | --- |
| **Red (Severe/Extreme)** | **9,084** | **49.7%** |
| Yellow (Moderate) | 4,008 | 21.9% |
| Orange (High) | 3,161 | 17.3% |
| Green (Low) | 2,012 | 11.0% |

Both files are **superseded** by the hourly pipeline and retained only for comparison.

---

## 3. `mort_21_Odisha.csv` — AHS mortality microdata

> ⚠️ **Pipe-delimited (`|`), not comma.** Reading it with default settings yields one column.

| Property | Value |
| --- | --- |
| Rows | **94,619** individual death records |
| Columns | 122 |
| Source | Annual Health Survey, Mortality Schedule, state 21 = Odisha |
| Districts | **All 30** (AHS codes 1–30) |
| Years | **2007–2011 only** |
| Weights | `wt` (survey weight, 88 distinct values) |

### 3.1 Structure

Three blocks denormalised onto each death record:

| Block | Columns | Describes |
| --- | --- | --- |
| Mortality | 1–36 | **The deceased** |
| Household / member | 37–105 | **The head of household** and dwelling |
| Survey admin | 106–122 | Weights, scheme, round |

> ⚠️ **The trap.** `sex`, `age`, and every asset column in the household block describe the **head of household**, not the deceased. Only `deceased_sex` and the three age-of-death columns describe the decedent. The AHS codebook states this explicitly; conflating them is an easy and invisible error.

### 3.2 Key fields

| Field | Values | Note |
| --- | --- | --- |
| `district` | 1–30 | AHS codes, **not** census or LGD |
| `rural` | 1 rural (81,468) / 2 urban (13,151) | |
| `deceased_sex` | 1 M (50,677) / 2 F (43,942) | |
| `year_of_death` | 2007–2011 | |
| `month_of_death` | 1–12, **0 = unknown** (1,939) | one stray `15`, 212 nulls |
| `date_of_death` | 1–31, **0 = unknown day (45,083 = 47.6%)** | |
| `age_of_death_below_one_month` | days (8,503 rows) | Three mutually exclusive age columns |
| `age_of_death_below_eleven_month` | months (4,141 rows) | must be unified into one `age_years` |
| `age_of_death_above_one_year` | years (81,975 rows; median 65) | |
| `place_of_death` | 1 home (71,249) / 2 transit / 3 facility (17,126) / 4 other | |
| `treatment_source` | 14 codes incl. `00` = no medical attention (20,015) | |
| `year` | 1/2/3 | **Survey round, not calendar year** |

Empty columns: `field38`, `isdeadmigrated`, `x`, `v126`. Names already stripped (anonymised).

### 3.3 What it supports

| Use | Viable? | Detail |
| --- | --- | --- |
| Daily statewide series | **Marginal** | 49,259 exact-day rows ≈ **27 deaths/day** statewide |
| Daily district series | **No** | ~**1.2 deaths/district-day** across the 5 study districts — far too sparse |
| Monthly district series | **Yes** | All 94,619 rows usable |
| Baseline rate by district × age × season | **Yes** | The local half of the risk model |
| Heat-specific cause analysis | **No** | **No ICD codes and no heat-stroke category anywhere in the schema.** Nearest environmental code is `Hypothermia-02` |

`death_symptoms` is populated on only 13.6% of rows and its 15 codes are child/neonatal-focused. The maternal module covers 645–765 rows.

### 3.4 ⚠️ Survey rounds 1 and 2 duplicate each other in 14 districts

In districts 1–10, 13–15 and 24, rounds 1 and 2 carry **identical record counts** (e.g. 2,469 and 2,469 for Bargarh). Matching on household, member serial, sex, date and age of death shows they are the **same deaths**: **23,269 duplicated records** in total, 23,263 of them in those 14 districts. The other 16 districts show zero overlap.

| | Before | After de-duplication |
| --- | --- | --- |
| Records | 94,619 | **71,350** |
| Weighted deaths | 1,713,541 | 1,267,880 |
| State crude death rate, 2007–09 | 10.3 / 1,000 | **6.97 / 1,000** |
| District CDR range | 0 – 20 | 2.2 – 10.6 (IQR 6.0 – 7.7) |

Left in, the duplication doubles recorded mortality in exactly those districts. `ushma.health.mortality.load_deaths` removes it before anything else is computed.

Coverage also differs by district: 14 districts report 2007–09 and 2011, 16 report all five years, and two (Nayagarh, Malkangiri) only 2010–11. District levels therefore use the median of each district's own non-zero years.

### 3.5 ⚠️ The blocking constraint

| Dataset | Period |
| --- | --- |
| Mortality | **2007 – 2011** |
| Hourly weather | **2015 – 2025** |
| **Overlap** | **Zero days** |

A heat→mortality exposure–response function **cannot be fitted from these two files**, however the joins are written.

**Observed seasonality** (exact-day rows) also runs counter to a naive heat signal:

| Month | Deaths | | Month | Deaths |
| --- | --- | --- | --- | --- |
| Jan | 4,339 | | Jul | 4,086 |
| Feb | 3,391 | | **Aug** | **5,644** |
| Mar | 3,660 | | Sep | 3,751 |
| Apr | 3,121 | | Oct | 4,400 |
| May | 3,462 | | Nov | 4,628 |
| Jun | 4,093 | | Dec | 4,684 |

Peaks in **August and December–January**, not April–June. Partly genuine (monsoon infectious disease, winter cardiorespiratory), partly survey recall artefact, and the 47.6% missing-day rows are not missing at random. Reported as found; see `05_MORTALITY_RISK_MODEL.md` for the consequences.

---

## 4. `Data_structure_AHS.xlsx` — the codebook

Requires `openpyxl`. **Without this file the mortality CSV is 122 columns of undecodable integers.**

| Sheet | Rows | Content |
| --- | --- | --- |
| `File Name` | 49 | Folder/file inventory (COMB, MORT, WOMAN, WPS × 9 states) |
| `State District Codes` | 295 | **Authoritative district decoder** |
| `Schedule Codes` | 7 | HL, HH, WS, WS-I, WS-II, **M = Mortality** |
| `COMB` / `MORT` / `WOMAN` / `WPS` | 16,388 each | Field dictionaries; MORT has **129 named fields** |

### Odisha district codes (state 21)

| | | | | | |
| --- | --- | --- | --- | --- | --- |
| 1 BARGARH | 6 KENDUJHAR | 11 JAGATSINGHAPUR | 16 NAYAGARH | 21 KANDHAMAL | 26 KALAHANDI |
| 2 JHARSUGUDA | 7 MAYURBHANJ | 12 CUTTACK | 17 KHORDHA | 22 BAUDH | 27 RAYAGADA |
| 3 SAMBALPUR | 8 BALESHWAR | 13 JAJAPUR | 18 PURI | 23 SONAPUR | 28 NABARANGAPUR |
| 4 DEBAGARH | 9 BHADRAK | 14 DHENKANAL | 19 GANJAM | 24 BALANGIR | 29 KORAPUT |
| 5 SUNDARGARH | 10 KENDRAPARA | 15 ANUGUL | 20 GAJAPATI | 25 NUAPADA | 30 MALKANGIRI |

---

## 5. `india_district_hvi_final.csv` — Heat Vulnerability Index

793 districts × 31 columns, 37 states/UTs.

| Pillar | Columns |
| --- | --- |
| **Exposure** | `lst_day_mean`, `lst_afternoon_mean`, `viirs_ntl_mean`, `built_surface_mean`, `smod_mean`, `building_height_mean`, `urban_lc_fraction` |
| **Sensitivity** | `pop_total`, `ghsl_pop_2025`, `children_pct`, `elderly_pct`, `female_pct` |
| **Adaptive capacity** | `ndvi_mean`, `evi_mean`, `green_fraction`, `forest_fraction`, `cropland_fraction`, `healthcare_travel_min`, `mpi_poverty_pct`, `literacy_pct`, `outdoor_workers_pct`, `sc_st_pct` |
| **Composite** | `exposure_score`, `sensitivity_score`, `adaptive_score`, `hvi_score` (0–100), `hvi_tier` |

### ⚠️ Four columns carry no information within Odisha

`mpi_poverty_pct` (25.83), `literacy_pct` (75.8), `outdoor_workers_pct` (40.69), `sc_st_pct` (24.67) are a **national fallback block — identical across all 30 Odisha districts.** `literacy_pct` has only 29 distinct values across all 793 national rows.

Using the HVI as-is would give every Odisha district the same socio-economic vulnerability. This is why NFHS-5 extraction (§7) is not optional.

The remote-sensing columns *do* vary meaningfully and are kept.

`dist_code` is mixed-type (mostly numeric strings, some alphanumeric elsewhere in India) — **parse as string**.

---

## 6. `odisha_5districts_hvi.csv`

Straight 5-row subset (BALANGIR, BALASORE, SAMBALPUR, KHORDHA, SUNDARGARH), schema identical to the parent.

| District | `hvi_score` | Tier |
| --- | --- | --- |
| BALANGIR | 80.43 | Very High |
| BALASORE | 75.69 | High |
| KHORDHA | 71.86 | High |
| SUNDARGARH | 61.41 | High |
| SAMBALPUR | 54.38 | Moderate |

> These are **not** Odisha's five most vulnerable districts. Jajapur (80.46) and Bhadrak (80.43) outrank most of them. USHMA therefore covers all 30 and keeps these five as the demo narrative.

---

## 7. `Odisha.pdf` — NFHS-5 (2020-21) fact sheets

~187 pages: Odisha state sheet plus **all 30 district fact sheets** at 6-page intervals. Ministry of Health & Family Welfare / IIPS.

The best available recent district-level demographic and health source in the folder, and its district names align with the AHS 30-district list. Provides real, varying values for household electricity, housing, cooking fuel, drinking water, anaemia, hypertension, diabetes and insurance coverage — **replacing the four flat HVI columns**.

---

## 8. `NCRB_ADSI_2023.pdf` — external validation anchor

Accidental Deaths & Suicides in India 2023, National Crime Records Bureau.

| Source | Figure |
| --- | --- |
| **Odisha 2023 Heat/Sun Stroke deaths** | **73** (58 M / 15 F) — Table 1.9, p.37 |
| All-India 2023 | 804 (12.5% of Forces-of-Nature deaths), up 10.1% on 2022's 730 |

**Annual, state-level, police-reported.** No district, no date of death — it cannot feed a daily or district series. It is a **validation benchmark only**, and a severe undercount of true heat-attributable mortality, so the test is order-of-magnitude plausibility and year-to-year direction, never equality.

---

## 9. Three incompatible district keys

| Source | Key | Example |
| --- | --- | --- |
| AHS mortality | integer 1–30 | `17` = KHORDHA |
| HVI | `dist_code` string, 370–399 for Odisha | `386` = KHORDHA |
| Weather files | `District_City` string | `Khordha_Bhubaneswar` |

Spellings diverge as well:

| HVI | AHS |
| --- | --- |
| `KEONJHAR (KENDUJHAR)` | `KENDUJHAR` |
| `NUAPARHA` | `NUAPADA` |
| `RAYAGARHA` | `RAYAGADA` |
| `SUBARNAPUR` | `SONAPUR` |
| `BALASORE` | `BALESHWAR` |
| `DEOGARH` | `DEBAGARH` |
| `JAGATSINGHPUR` | `JAGATSINGHAPUR` |

Resolved by one reviewed crosswalk (`ushma.geo.districts`) carrying the Census 2011 codes (361–390, same order as AHS 1–30), with a test asserting **every key resolves and no row is dropped on any join**. Silent join failure is the most common way a pipeline like this produces confident nonsense.

---

## 10. Provenance and handling

- **Source files are never modified or moved.** `config.Paths.raw_dir` points at the project root and reads in place; only derived artefacts are written under `data/`.
- The 2 GB hourly folder is **not** copied into `data/raw` — duplicating it would waste disk and create two sources of truth.
- Mortality microdata is individual-level. It stays out of the repo, out of the API, and out of any artefact above district-month aggregation.
