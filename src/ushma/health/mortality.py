"""AHS mortality microdata: decoding, aggregation and the fitted baseline.

What this data can and cannot do
--------------------------------
``mort_21_Odisha.csv`` holds 94,619 individual death records from the Annual
Health Survey (Odisha, 2007-2011). It is the only individual-level health data
supplied, and it has three properties that decide how it is used:

1. **It does not overlap the weather record** (2015-2025), so it cannot be used
   to fit a heat exposure-response curve. It *can* be used to fit the baseline:
   how many deaths to expect, where, at what age and in which season.
2. **About half of records have an unknown day of death** (``date_of_death == 0``;
   47.6% before de-duplication, 45.4% after).
   Monthly series use every record; daily series are built only from the
   exact-day rows and are used for shape, never for level.
3. **It is a weighted sample**, and survey coverage differs by district: 14
   districts report deaths for 2007-2009 and 2011 only, the other 16 across all
   five years, and two (Nayagarh, Malkangiri) only for 2010-2011. Annual totals
   are therefore not comparable across districts year by year; each district's
   level is taken as the median of its own non-zero yearly totals.
4. **Rounds 1 and 2 duplicate each other in 14 districts.** 23,269 records
   appear twice -- identical household, member serial, sex, date and age of
   death -- 23,263 of them in districts 1-10, 13-15 and 24. Left in, this
   doubles recorded mortality in exactly those districts. Records are
   de-duplicated on the decedent key before anything else is computed.

The household-head trap
-----------------------
The file denormalises the household and head-of-household records onto each
death. ``sex`` and ``age`` in that block describe the **head of household**, not
the deceased; only ``deceased_sex`` and the three ``age_of_death_*`` columns
describe the decedent. This module reads only the decedent columns.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ushma.config import settings
from ushma.geo.districts import district_table
from ushma.logging_setup import get_logger

log = get_logger(__name__)

__all__ = [
    "read_codebook_districts",
    "load_deaths",
    "monthly_district_deaths",
    "seasonal_profile",
    "build_baseline",
]

DECEDENT_COLUMNS = [
    "district",
    "hl_id",
    "house_no",
    "house_hold_no",
    "m_serial_no",
    "year",
    "rural",
    "deceased_sex",
    "date_of_death",
    "month_of_death",
    "year_of_death",
    "age_of_death_below_one_month",
    "age_of_death_below_eleven_month",
    "age_of_death_above_one_year",
    "place_of_death",
    "wt",
]

#: Years used for the seasonal profile (all districts report a full year).
COMPLETE_YEARS = (2007, 2008, 2009)

#: The decedent identity used to detect records duplicated across survey rounds.
DEDUP_KEY = [
    "district", "hl_id", "house_no", "house_hold_no", "m_serial_no",
    "deceased_sex", "date_of_death", "month_of_death", "year_of_death",
    "age_of_death_above_one_year",
]

AGE_BANDS = [(0, 5, "0-4"), (5, 15, "5-14"), (15, 45, "15-44"), (45, 65, "45-64"), (65, 200, "65+")]


def read_codebook_districts() -> pd.DataFrame:
    """Odisha's district decoder from the official AHS codebook."""
    import openpyxl

    wb = openpyxl.load_workbook(settings.paths.ahs_codebook_xlsx, read_only=True)
    ws = wb["State District Codes"]
    rows = []
    for r in ws.iter_rows(values_only=True):
        if not r or r[0] is None or r[1] is None:
            continue
        try:
            state, code = int(r[0]), int(r[1])
        except (TypeError, ValueError):
            continue
        if state == 21:
            rows.append({"ahs_code": code, "codebook_name": str(r[2]).strip()})
    wb.close()
    return pd.DataFrame(rows)


def _age_years(df: pd.DataFrame) -> np.ndarray:
    """Unify the three mutually exclusive age-of-death columns into years."""
    days = pd.to_numeric(df["age_of_death_below_one_month"], errors="coerce")
    months = pd.to_numeric(df["age_of_death_below_eleven_month"], errors="coerce")
    years = pd.to_numeric(df["age_of_death_above_one_year"], errors="coerce")
    age = years.copy()
    age = age.where(age.notna(), months / 12.0)
    age = age.where(age.notna(), days / 365.25)
    return age.to_numpy(dtype=float)


def load_deaths() -> pd.DataFrame:
    """Decedent-level frame with a unified age and a calendar date where known."""
    df = pd.read_csv(
        settings.paths.mortality_csv,
        sep="|",
        usecols=DECEDENT_COLUMNS,
        low_memory=False,
    )
    n_raw = len(df)
    df = df.rename(columns={"year": "survey_round"})
    dup = df.duplicated(subset=DEDUP_KEY, keep="first")
    df = df[~dup].reset_index(drop=True)
    log.info("deaths: removed %s records duplicated across survey rounds (%s -> %s)",
             f"{int(dup.sum()):,}", f"{n_raw:,}", f"{len(df):,}")
    df["age_years"] = _age_years(df)
    df["ahs_code"] = pd.to_numeric(df["district"], errors="coerce").astype("Int64")

    y = pd.to_numeric(df["year_of_death"], errors="coerce")
    m = pd.to_numeric(df["month_of_death"], errors="coerce")
    d = pd.to_numeric(df["date_of_death"], errors="coerce")
    df["year"] = y
    df["month"] = m.where(m.between(1, 12))
    df["day_known"] = d.between(1, 31) & df["month"].notna() & y.between(2007, 2011)

    date = pd.to_datetime(
        dict(year=y.where(df["day_known"]), month=df["month"].where(df["day_known"]), day=d.where(df["day_known"])),
        errors="coerce",
    )
    df["date"] = date
    df["day_known"] = df["day_known"] & df["date"].notna()

    bands = pd.Series(pd.NA, index=df.index, dtype="object")
    for lo, hi, label in AGE_BANDS:
        bands[(df["age_years"] >= lo) & (df["age_years"] < hi)] = label
    df["age_band"] = bands
    df["wt"] = pd.to_numeric(df["wt"], errors="coerce").fillna(0.0)

    log.info(
        "deaths: %s records | exact day %s (%.1f%%) | weighted total %s",
        f"{len(df):,}",
        f"{int(df['day_known'].sum()):,}",
        100 * df["day_known"].mean(),
        f"{df['wt'].sum():,.0f}",
    )
    return df


def monthly_district_deaths(deaths: pd.DataFrame) -> pd.DataFrame:
    """Weighted deaths per district per calendar month (all records with a month)."""
    m = deaths[deaths["month"].notna() & deaths["year"].between(2007, 2011)]
    return (
        m.groupby(["ahs_code", "year", "month"])
        .agg(deaths_weighted=("wt", "sum"), records=("wt", "size"))
        .reset_index()
    )


def seasonal_profile(deaths: pd.DataFrame, harmonics: int = 2) -> pd.DataFrame:
    """Smoothed day-of-year mortality multiplier, mean 1.0 over the year.

    Estimated from weighted monthly counts across all districts (the district
    series are too sparse to support their own seasonal shape) with a
    ``harmonics``-term Fourier fit, so a noisy month does not print through as a
    step in the baseline.
    """
    m = deaths[deaths["month"].notna() & deaths["year"].isin(COMPLETE_YEARS)]
    monthly = m.groupby("month")["wt"].sum().reindex(range(1, 13)).fillna(0.0)
    days_in_month = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
    per_day = monthly.to_numpy() / days_in_month
    rel = per_day / per_day.mean()

    # Fourier fit on mid-month day-of-year.
    mid = np.cumsum(days_in_month) - days_in_month / 2
    theta = 2 * np.pi * mid / 365.25
    cols = [np.ones_like(theta)]
    for k in range(1, harmonics + 1):
        cols += [np.cos(k * theta), np.sin(k * theta)]
    X = np.column_stack(cols)
    coef, *_ = np.linalg.lstsq(X, rel, rcond=None)

    doy = np.arange(1, 366)
    th = 2 * np.pi * (doy - 0.5) / 365.25
    cols = [np.ones_like(th)]
    for k in range(1, harmonics + 1):
        cols += [np.cos(k * th), np.sin(k * th)]
    fit = np.column_stack(cols) @ coef
    fit = fit / fit.mean()

    prof = pd.DataFrame({"doy": doy, "seasonal_factor": fit.astype(np.float32)})
    prof.attrs["monthly_relative"] = dict(zip(range(1, 13), np.round(rel, 3).tolist()))
    return prof


def build_baseline(deaths: pd.DataFrame | None = None) -> pd.DataFrame:
    """Expected all-cause deaths per district per day of year, at today's population.

    Composition::

        expected(d, doy) = CDR_now * rel_rate(d) * pop_now(d) / 365 * seasonal(doy)

    * ``rel_rate(d)`` -- district crude death rate relative to the state, from
      AHS weighted deaths 2007-2009 over Census 2011 population. *Fitted locally.*
    * ``seasonal(doy)`` -- smoothed Fourier profile. *Fitted locally.*
    * ``CDR_now`` -- current statewide crude death rate, a configurable anchor.
      Mortality has fallen since 2007-09, so the AHS absolute level is used for
      relative structure only.
    * ``pop_now(d)`` -- Census 2011 scaled by a configurable growth factor.
    """
    deaths = deaths if deaths is not None else load_deaths()
    cfg = settings.risk
    dt = district_table()

    full = deaths[deaths["year"].between(2007, 2011)]
    yearly = full.groupby(["ahs_code", "year"])["wt"].sum()
    # Median of each district's own non-zero years: robust to the partial
    # 2011 round and to districts the survey only reached in 2010-2011.
    annual = yearly[yearly > 0].groupby(level=0).median()
    dt = dt.merge(annual.rename("ahs_annual_deaths"), left_on="ahs_code", right_index=True, how="left")
    dt["ahs_cdr"] = 1000.0 * dt["ahs_annual_deaths"] / dt["pop_2011"]
    state_cdr = 1000.0 * dt["ahs_annual_deaths"].sum() / dt["pop_2011"].sum()
    dt["rel_rate_raw"] = dt["ahs_cdr"] / state_cdr
    # Bounded: after de-duplication the district spread is plausible (IQR
    # 6.0-7.7 per 1,000) except for a few thinly surveyed districts -- Kandhamal
    # comes out at 2.2 -- where a coverage artefact would otherwise drive a
    # threefold difference in predicted heat risk.
    dt["rel_rate"] = dt["rel_rate_raw"].clip(0.7, 1.4)

    elderly = (
        full.assign(is65=full["age_years"] >= 65)
        .groupby("ahs_code")
        .apply(lambda g: float((g["wt"] * g["is65"]).sum() / max(g["wt"].sum(), 1e-9)), include_groups=False)
        .rename("deaths_share_65plus")
    )
    dt = dt.merge(elderly, left_on="ahs_code", right_index=True, how="left")

    dt["pop_now"] = (dt["pop_2011"] * cfg.population_growth_since_2011).round().astype(int)
    dt["cdr_now"] = cfg.current_cdr_per_1000 * dt["rel_rate"]
    dt["daily_deaths_mean"] = dt["cdr_now"] / 1000.0 * dt["pop_now"] / 365.0

    prof = seasonal_profile(deaths)
    base = dt[["ahs_code", "district", "pop_now", "cdr_now", "rel_rate", "daily_deaths_mean", "deaths_share_65plus"]]
    grid = base.merge(prof, how="cross")
    grid["expected_deaths"] = (grid["daily_deaths_mean"] * grid["seasonal_factor"]).astype(np.float32)
    grid["rate_per_100k_day"] = (1e5 * grid["expected_deaths"] / grid["pop_now"]).astype(np.float32)

    out = settings.paths.processed_dir / "baseline_mortality.parquet"
    grid.to_parquet(out, index=False)
    dt.to_parquet(settings.paths.processed_dir / "district_mortality_summary.parquet", index=False)
    log.info(
        "baseline: AHS state CDR %.2f/1000 (2007-09) -> anchored %.2f/1000 now | %s expected deaths/yr",
        state_cdr,
        cfg.current_cdr_per_1000,
        f"{dt['daily_deaths_mean'].sum() * 365:,.0f}",
    )
    grid.attrs["ahs_state_cdr"] = state_cdr
    grid.attrs["monthly_relative"] = prof.attrs["monthly_relative"]
    return grid
