"""District-level historical risk series and the NCRB sanity check.

Aggregates cell HTSI to districts (mean over the cells each district owns),
applies the risk model day by day for 2015-2025, and compares the statewide
annual total of heat-attributable deaths with the NCRB heat/sunstroke count.

That comparison is a *plausibility* check, not a validation of calibration:
NCRB counts police-reported deaths certified as heatstroke, a small and
severely under-ascertained subset of heat-attributable all-cause mortality.
Studies that estimate both routinely find attributable deaths one to two orders
of magnitude above certified heatstroke. The test is therefore order of
magnitude and direction, never equality.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ushma.config import settings
from ushma.health.risk import excess_deaths, lag_matrix, load_exposure_response
from ushma.logging_setup import get_logger

log = get_logger(__name__)

#: NCRB ADSI 2023, Table 1.9 (Odisha, Heat/Sun Stroke, all genders).
NCRB_ODISHA_HEATSTROKE = {2023: 73}


def _doy(dates: pd.Series) -> np.ndarray:
    ts = pd.DatetimeIndex(dates)
    d = ts.dayofyear.to_numpy().copy()
    d[np.asarray(ts.is_leap_year) & (d > 59)] -= 1
    return d


def build_district_risk() -> pd.DataFrame:
    htsi = pd.read_parquet(
        settings.paths.processed_dir / "daily_htsi.parquet",
        columns=["cell_id", "date", "htsi", "wbgt_max", "utci_max", "t2m_max", "wbgt_night_min"],
    )
    cells = pd.read_parquet(settings.paths.processed_dir / "cell_district.parquet")
    cells = cells[cells["in_odisha"]][["cell_id", "ahs_code"]]
    h = htsi.merge(cells, on="cell_id", how="inner")
    # Full calendar years only (the file-year partitions bleed a day at each end).
    h = h[(h["date"] >= "2015-01-01") & (h["date"] <= "2025-12-31")]

    daily = (
        h.groupby(["ahs_code", "date"])
        .agg(htsi=("htsi", "mean"), htsi_max=("htsi", "max"), wbgt_max=("wbgt_max", "mean"),
             utci_max=("utci_max", "mean"), t2m_max=("t2m_max", "mean"),
             wbgt_night_min=("wbgt_night_min", "mean"))
        .reset_index()
        .sort_values(["ahs_code", "date"])
    )
    daily["doy"] = _doy(daily["date"])

    base = pd.read_parquet(settings.paths.processed_dir / "baseline_mortality.parquet")
    vuln = pd.read_parquet(settings.paths.processed_dir / "vulnerability.parquet")[["ahs_code", "vuln_mult"]]
    daily = daily.merge(base[["ahs_code", "doy", "expected_deaths", "pop_now"]], on=["ahs_code", "doy"], how="left")
    daily = daily.merge(vuln, on="ahs_code", how="left")
    daily["population"] = daily["pop_now"]
    daily["base_rate"] = daily["expected_deaths"] / daily["pop_now"]

    er = load_exposure_response()
    lags = lag_matrix(daily["htsi"], len(er.lag_weights), by=daily["ahs_code"])
    risk = excess_deaths(daily.drop(columns=["expected_deaths"]), lags, er)

    out = settings.paths.processed_dir / "district_risk_daily.parquet"
    risk.to_parquet(out, index=False, compression="zstd")
    log.info("district risk: %s district-days -> %s", f"{len(risk):,}", out.name)
    return risk


def annual_summary(risk: pd.DataFrame) -> pd.DataFrame:
    y = risk.assign(year=pd.DatetimeIndex(risk["date"]).year)
    s = y.groupby("year").agg(
        excess_deaths=("excess_deaths", "sum"),
        excess_low=("excess_deaths_low", "sum"),
        excess_high=("excess_deaths_high", "sum"),
        expected_deaths=("expected_deaths", "sum"),
    )
    s["attributable_fraction_pct"] = 100 * s["excess_deaths"] / s["expected_deaths"]
    s["ncrb_heatstroke"] = s.index.map(NCRB_ODISHA_HEATSTROKE)
    s["ratio_to_ncrb"] = s["excess_deaths"] / s["ncrb_heatstroke"]
    return s.round(2)
