# Places: Districts, Grid Cells and Wards

## 1. District crosswalk

Four sources, four naming schemes (`src/ushma/geo/districts.py`). One canonical table keyed on the AHS code, carrying the HVI spelling, NFHS spelling, Census 2011 code (361–390, same order as AHS 1–30), HQ, approximate centroid, area and Census 2011 population. Totals reconcile exactly: **41,974,218 people, 155,707 km²**.

`resolve()` maps any known spelling to the canonical code and **raises** on anything else. A test asserts every district in the HVI file and the AHS codebook resolves.

## 2. Cells → districts

No boundary polygons were supplied. Cells are assigned by (`geo/cells.py`):

1. **Sea mask** — an approximate coastline (Gopalpur → Chilika → Puri → Paradip → Dhamra → Chandipur → Talsari); 122 cells fall in the Bay of Bengal.
2. **Size-weighted nearest centroid** — distance to each district's centroid divided by its equivalent radius $\sqrt{A/\pi}$.
3. **Cut-off** at 1.2 radii, then an interior hole-fill.

Why not nearest headquarters: many HQs sit on a district edge. Nuapada (~3,850 km²) claimed 24 cells (~17,000 km²) of Chhattisgarh that way.

**Result: 234 in-state cells (~170,000 km², 9% over the true area), every district represented.** Small districts are under-resolved at 27 km (Jharsuguda gets one cell). A real district boundary file replaces this without touching downstream code.

## 3. Wards

### Contract for real boundaries

`data/geo/wards.geojson`, EPSG:4326, a FeatureCollection whose features carry:

| Property | Required | Notes |
| --- | --- | --- |
| `ward_id` | ✓ | unique |
| `ward_name` | ✓ | |
| `ulb_name` | ✓ | urban local body |
| `district` | ✓ | any spelling `resolve()` accepts |
| `population`, `elderly_pct`, `slum_pop_pct`, `built_up_frac`, `ndvi` | optional | filled from district values if absent; the fill is recorded per ward |

Convert a shapefile with `ogr2ogr -f GeoJSON -t_srs EPSG:4326 wards.geojson wards.shp`. The loader collects **every** problem and refuses to load a partially valid file.

### The synthetic stand-in (in use until real files arrive)

332 wards across the eight largest cities with their **real ward counts** — Bhubaneswar 67, Cuttack 59, Berhampur 42, Sambalpur 41, Rourkela 40, Puri 32, Balasore 30, Balangir 21 — laid out as Voronoi cells of an evenly spaced spiral inside each city's footprint. Attributes follow a seeded core-to-edge gradient (built-up, vegetation, density) with clustered slum pockets. **Every ward carries `synthetic: true` and the dashboard says so.**

## 4. Downscaling to a ward

1. **Interpolation** — inverse-distance weights over the four nearest in-state cells.
2. **Urban heat island** (`geo/uhi.py`):

| | Formula | Dense core (0.9) | Edge (0.3) |
| --- | --- | --- | --- |
| Day | $0.30 + 1.55\,b$ °C | +1.7 °C | +0.8 °C |
| Night | $0.50 + 3.00\,b$ °C | +3.2 °C | +1.4 °C |

Published nocturnal UHI intensities for Indian cities are mostly 2–4 °C, so the defaults sit inside that range. The uplift is applied to UTCI and night WBGT, and ward HTSI is recomputed through HTSI's own intensity and night-relief scalings — not added as an arbitrary offset. Measured on the peak demo day (29 May 2024) the uplift is 0.6–7.6 HTSI points across the 332 wards, median 4.1 — dense cores highest.

3. **Ward vulnerability** = district score adjusted by the ward's elderly, slum and built-up shares relative to its city.

## 5. Honest limits

The grid is ~27 km; a ward is 1–5 km. Everything below grid scale here is a parameterisation. The replacement, in order of value: real ward boundaries → ward-level census attributes → satellite land-surface temperature per ward (MODIS/Landsat) → an urban canopy model.
