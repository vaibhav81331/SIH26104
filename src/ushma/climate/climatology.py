"""Day-of-year percentile climatology and the Excess Heat Factor.

Why relative thresholds
-----------------------
An absolute threshold ("alert above 45 degC") is the wrong instrument for a
population that is already acclimatised. The epidemiological literature is
consistent on this: mortality responds to how unusual conditions are *for that
place at that time of year*, far more than to the absolute number. A 40 degC day
in mid-May is ordinary in Bolangir and alarming in coastal Balasore, and a
warning system that cannot tell the difference will either miss the second or
cry wolf in the first.

So every alert threshold in USHMA is anchored to a per-cell, per-day-of-year
percentile computed from the 11-year record.

Window
------
Percentiles pool a +/-15 day window around each day of year. Over 11 years that
is ~341 samples per (cell, day-of-year) -- enough to estimate a 95th percentile
with a usable standard error, while still tracking the seasonal cycle.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ushma.config import settings
from ushma.logging_setup import get_logger

log = get_logger(__name__)

__all__ = ["build_climatology", "attach_anomaly", "excess_heat_factor"]


def _doy_no_leap(dates: pd.Series) -> np.ndarray:
    """Day of year on a fixed 365-day frame.

    29 February is folded onto day 59 so that a leap year does not shift every
    subsequent day's climatology by one.
    """
    ts = pd.DatetimeIndex(dates)
    doy = ts.dayofyear.to_numpy().copy()
    is_leap = np.asarray(ts.is_leap_year)
    after_feb29 = is_leap & (doy > 59)
    doy[after_feb29] -= 1
    return doy


def build_climatology(
    daily: pd.DataFrame,
    value_cols: tuple[str, ...] = ("wbgt_max", "utci_max", "t2m_max", "wbgt_night_min"),
    window_days: int | None = None,
    percentiles: tuple[float, ...] | None = None,
    out_path: Path | None = None,
    cell_chunk: int = 60,
) -> pd.DataFrame:
    """Per-cell, per-day-of-year percentiles over the full record.

    Returns a long frame keyed ``(cell_id, doy)`` with one column per
    ``{value}_p{percentile}``.
    """
    window = window_days or settings.climatology.doy_window_days
    pcts = np.asarray(percentiles or settings.climatology.percentiles, dtype=np.float64)

    df = daily.copy()
    df["doy"] = _doy_no_leap(df["date"])
    df["year"] = pd.DatetimeIndex(df["date"]).year

    cells = np.sort(df["cell_id"].unique())
    years = np.sort(df["year"].unique())
    cell_ix = {c: i for i, c in enumerate(cells)}
    year_ix = {y: i for i, y in enumerate(years)}

    ci = df["cell_id"].map(cell_ix).to_numpy()
    yi = df["year"].map(year_ix).to_numpy()
    di = df["doy"].to_numpy() - 1

    # Dense (cell, year, doy) cube per variable. NaN marks absent days, which
    # nanpercentile ignores -- so partial years at the record's edges do not
    # need special handling.
    shape = (len(cells), len(years), 365)
    cubes = {}
    for col in value_cols:
        cube = np.full(shape, np.nan, dtype=np.float32)
        cube[ci, yi, di] = df[col].to_numpy(dtype=np.float32)
        cubes[col] = cube

    # For each day of year, pool the +/-window days across all years and take
    # the percentiles in one vectorised call. 365 calls on a (cells, samples)
    # array, rather than one call per (cell, doy, column, percentile) group --
    # which is 2.8 M Python-level calls and takes over an hour.
    offsets = np.arange(-window, window + 1)
    out = {col: np.empty((len(cells), 365, len(pcts)), dtype=np.float32) for col in value_cols}

    for d in range(365):
        idx = (d + offsets) % 365
        for col in value_cols:
            pooled = cubes[col][:, :, idx].reshape(len(cells), -1)
            with np.errstate(invalid="ignore"):
                out[col][:, d, :] = np.nanpercentile(pooled, pcts, axis=1).T
        if (d + 1) % 90 == 0:
            log.info("climatology: day-of-year %d/365", d + 1)

    frame = {
        "cell_id": np.repeat(cells, 365),
        "doy": np.tile(np.arange(1, 366), len(cells)),
    }
    for col in value_cols:
        for j, pct in enumerate(pcts):
            frame[f"{col}_p{int(pct)}"] = out[col][:, :, j].reshape(-1)
    clim = pd.DataFrame(frame)

    for c in clim.columns:
        if clim[c].dtype == np.float64:
            clim[c] = clim[c].astype(np.float32)

    out_path = Path(out_path or settings.paths.climatology_parquet)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clim.to_parquet(out_path, index=False, compression="zstd")
    log.info("climatology -> %s | %s rows | %d cells",
             out_path, f"{len(clim):,}", clim["cell_id"].nunique())
    return clim


def attach_anomaly(
    daily: pd.DataFrame,
    clim: pd.DataFrame,
    value_col: str = "wbgt_max",
) -> pd.DataFrame:
    """Join climatology onto daily records and compute the anomaly percentile.

    ``{value}_pct_rank`` is where today sits within its own day-of-year
    distribution, interpolated between the stored percentile breakpoints. This
    is the quantity HTSI's anomaly component consumes, and it is what makes the
    index comparable between a coastal and an inland ward.
    """
    df = daily.copy()
    df["doy"] = _doy_no_leap(df["date"])
    merged = df.merge(clim, on=["cell_id", "doy"], how="left")

    pcts = sorted(settings.climatology.percentiles)
    breaks = [f"{value_col}_p{int(p)}" for p in pcts]
    missing = [b for b in breaks if b not in merged.columns]
    if missing:
        raise KeyError(f"climatology is missing {missing}; rebuild it for {value_col}")

    v = merged[value_col].to_numpy(dtype=np.float64)
    bvals = np.column_stack([merged[b].to_numpy(dtype=np.float64) for b in breaks])
    pct_axis = np.asarray(pcts, dtype=np.float64)

    # Piecewise-linear interpolation of the rank, extrapolated flat below the
    # lowest stored break and linearly above the highest.
    rank = np.full(v.shape, np.nan)
    below = v <= bvals[:, 0]
    rank[below] = pct_axis[0] * (v[below] / np.maximum(bvals[below, 0], 1e-6))

    for i in range(len(pcts) - 1):
        lo, hi = bvals[:, i], bvals[:, i + 1]
        seg = (v > lo) & (v <= hi)
        span = np.maximum(hi - lo, 1e-6)
        rank[seg] = pct_axis[i] + (pct_axis[i + 1] - pct_axis[i]) * (v[seg] - lo[seg]) / span[seg]

    above = v > bvals[:, -1]
    # Above the top break, scale the remaining headroom to 100 using the width
    # of the last segment as a ruler.
    last_span = np.maximum(bvals[:, -1] - bvals[:, -2], 1e-6)
    rank[above] = np.minimum(
        100.0,
        pct_axis[-1] + (100.0 - pct_axis[-1]) * (v[above] - bvals[above, -1]) / last_span[above],
    )

    merged[f"{value_col}_pct_rank"] = np.clip(rank, 0.0, 100.0).astype(np.float32)
    return merged


def excess_heat_factor(
    daily: pd.DataFrame,
    value_col: str = "t2m_mean",
    clim: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Excess Heat Factor (Nairn & Fawcett, Australian BOM).

    EHF combines two ideas that a single-day threshold cannot express:

    ``EHI_sig``  = mean of the last 3 days  -  the 95th percentile of climatology
        How hot it is in absolute, climatological terms.

    ``EHI_accl`` = mean of the last 3 days  -  mean of the preceding 30 days
        Whether the population has had a chance to acclimatise. The same
        temperature arriving after a cool spell is markedly more dangerous.

    ``EHF = EHI_sig * max(1, EHI_accl)``

    It is the best externally validated single predictor of heat mortality in
    operational use anywhere, and is essentially absent from Indian warning
    systems.
    """
    df = daily.sort_values(["cell_id", "date"]).copy()
    g = df.groupby("cell_id", sort=False)[value_col]

    three = g.transform(lambda s: s.rolling(3, min_periods=3).mean())
    # The 30-day acclimatisation window ends the day before the 3-day window
    # begins, so the two do not overlap.
    thirty = g.transform(
        lambda s: s.shift(3).rolling(30, min_periods=30).mean()
    )

    if clim is not None:
        df["doy"] = _doy_no_leap(df["date"])
        p95_col = f"{value_col}_p95"
        if p95_col not in clim.columns:
            raise KeyError(f"climatology has no {p95_col}")
        df = df.merge(clim[["cell_id", "doy", p95_col]], on=["cell_id", "doy"], how="left")
        p95 = df[p95_col].to_numpy(dtype=np.float64)
    else:
        # Fall back to a single per-cell 95th percentile across the record.
        p95 = df.groupby("cell_id")[value_col].transform(
            lambda s: np.nanpercentile(s, 95)
        ).to_numpy(dtype=np.float64)

    ehi_sig = three.to_numpy(dtype=np.float64) - p95
    ehi_accl = three.to_numpy(dtype=np.float64) - thirty.to_numpy(dtype=np.float64)

    df["ehi_sig"] = ehi_sig.astype(np.float32)
    df["ehi_accl"] = ehi_accl.astype(np.float32)
    df["ehf"] = (ehi_sig * np.maximum(1.0, ehi_accl)).astype(np.float32)
    return df
