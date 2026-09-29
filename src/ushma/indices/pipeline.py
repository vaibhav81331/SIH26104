"""Compute hourly thermal indices and aggregate them to daily cell records.

This is where the project's central methodological claim is implemented: indices
are evaluated at the native hourly resolution, where temperature, humidity, wind
and radiation are physically consistent with one another, and only then
aggregated. Collapsing the inputs to daily statistics first -- pairing the day's
maximum temperature with the day's mean humidity -- describes an hour that never
happened.

Aggregates produced per cell per IST day
----------------------------------------
``*_max`` / ``*_mean``
    Conventional daily statistics of each index.
``*_night_min``
    Minimum over the 22:00-06:00 IST window. Overnight heat that never releases
    is among the strongest predictors of heat mortality and is invisible to any
    daytime-maximum warning.
``wbgt_degree_hours``
    Cumulative degree-hours above a threshold: intensity and duration combined.
``wbgt_hours_above_*``
    Count of hours over each risk threshold -- the exposure window an outdoor
    worker actually faces.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ushma.config import settings
from ushma.indices.heat_index import heat_index
from ushma.indices.psychro import relative_humidity, wind_at_height
from ushma.indices.solar import solar_geometry
from ushma.indices.utci import (
    mean_radiant_temperature,
    mean_radiant_temperature_human,
    utci,
)
from ushma.indices.wbgt import wbgt_liljegren, wbgt_shade
from ushma.logging_setup import get_logger

log = get_logger(__name__)

#: Hourly WBGT thresholds whose exceedance hours we count.
WBGT_HOUR_THRESHOLDS = (28.0, 30.0, 32.0, 35.0)


def compute_hourly_indices(cell: pd.DataFrame, lat: float, lon: float) -> pd.DataFrame:
    """Evaluate every thermal index on one cell's hourly record."""
    ta = cell["T2M"].to_numpy(dtype=np.float64)
    td = cell["T2MDEW"].to_numpy(dtype=np.float64)
    ws10 = cell["WS10M"].to_numpy(dtype=np.float64)
    ps = cell["PS"].to_numpy(dtype=np.float64)
    ghi = cell["ALLSKY_SFC_SW_DWN"].to_numpy(dtype=np.float64)

    sol = solar_geometry(cell["ts_utc"], lat, lon, ghi)
    cos_z = sol["cos_zenith"].to_numpy(dtype=np.float64)
    fdir = sol["direct_fraction"].to_numpy(dtype=np.float64)

    # RH recomputed from dewpoint rather than taken from RH2M: it is consistent
    # with the vapour pressure every other index uses, and bounded at 100%.
    rh = relative_humidity(ta, td)
    ws2 = wind_at_height(ws10)

    w = wbgt_liljegren(
        t_c=ta, dewpoint_c=td, wind_ms=ws2, pressure_kpa=ps,
        solar_wm2=ghi, cos_zenith=cos_z, direct_fraction=fdir,
    )
    # Two radiant temperatures, deliberately:
    #   tmrt_globe -- what a black globe sees, the basis of WBGT.
    #   tmrt       -- what a standing person sees, which is what UTCI is
    #                 defined against. Feeding the globe value into UTCI
    #                 overstates peak Tmrt by ~30 degC and saturates the index.
    tmrt_globe = mean_radiant_temperature(w["tg"], ta, ws2)
    tmrt = mean_radiant_temperature_human(ta, td, ghi, cos_z, fdir)

    out = pd.DataFrame(
        {
            "cell_id": cell["cell_id"].to_numpy(),
            "ts_ist": cell["ts_ist"].to_numpy(),
            "t2m": ta.astype(np.float32),
            "rh": rh.astype(np.float32),
            "wbgt": w["wbgt"].astype(np.float32),
            "tg": w["tg"].astype(np.float32),
            "tnwb": w["tnwb"].astype(np.float32),
            "tmrt": tmrt.astype(np.float32),
            "tmrt_globe": tmrt_globe.astype(np.float32),
            "utci": utci(ta, tmrt, ws10, rh).astype(np.float32),
            "heat_index": heat_index(ta, rh).astype(np.float32),
            # Retained purely as the comparison baseline.
            "wbgt_shade": wbgt_shade(ta, rh).astype(np.float32),
        }
    )
    return out


def aggregate_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    """Collapse hourly indices to one row per cell per IST day."""
    h = hourly.copy()
    ts = pd.DatetimeIndex(h["ts_ist"])
    h["date"] = ts.normalize()
    hour = ts.hour

    night_start = settings.indices.night_start_hour
    night_end = settings.indices.night_end_hour
    # The night window wraps midnight, so it is a union, not a range.
    h["is_night"] = (hour >= night_start) | (hour < night_end)

    index_cols = ["t2m", "wbgt", "utci", "heat_index", "tmrt", "wbgt_shade"]
    agg = {c: ["max", "mean", "min"] for c in index_cols}
    daily = h.groupby(["cell_id", "date"]).agg(agg)
    daily.columns = [f"{c}_{s}" for c, s in daily.columns]
    daily = daily.reset_index()

    # Night-time minima: assign each night to the day it *ends* on, so that the
    # 22:00 reading belongs with the following morning's recovery period.
    night = h[h["is_night"]].copy()
    night_ts = pd.DatetimeIndex(night["ts_ist"])
    night["night_of"] = np.where(
        night_ts.hour >= night_start,
        (night_ts + pd.Timedelta(days=1)).normalize(),
        night_ts.normalize(),
    )
    nightly = (
        night.groupby(["cell_id", "night_of"])[["t2m", "wbgt", "utci"]]
        .min()
        .rename(columns=lambda c: f"{c}_night_min")
        .reset_index()
        .rename(columns={"night_of": "date"})
    )
    daily = daily.merge(nightly, on=["cell_id", "date"], how="left")

    # Duration metrics on the hourly WBGT.
    thr = settings.indices.wbgt_degree_hour_threshold
    h["excess"] = np.maximum(h["wbgt"].to_numpy() - thr, 0.0)
    dh = h.groupby(["cell_id", "date"])["excess"].sum().rename("wbgt_degree_hours")
    daily = daily.merge(dh.reset_index(), on=["cell_id", "date"], how="left")

    for t in WBGT_HOUR_THRESHOLDS:
        col = f"wbgt_hours_above_{int(t)}"
        counts = (
            h.assign(_f=(h["wbgt"] >= t).astype(np.int16))
            .groupby(["cell_id", "date"])["_f"]
            .sum()
            .rename(col)
        )
        daily = daily.merge(counts.reset_index(), on=["cell_id", "date"], how="left")

    for c in daily.columns:
        if daily[c].dtype == np.float64:
            daily[c] = daily[c].astype(np.float32)
    return daily


def build_daily(
    years: list[int] | None = None,
    out_path: Path | None = None,
    keep_hourly: bool = False,
) -> pd.DataFrame:
    """Run the index pipeline across the whole panel and write daily records."""
    settings.paths.ensure_dirs()
    root = settings.paths.hourly_grid_dir
    parts = sorted(root.glob("year=*/part.parquet"))
    if years:
        keep = {str(y) for y in years}
        parts = [p for p in parts if p.parent.name.split("=")[1] in keep]
    if not parts:
        raise FileNotFoundError(f"No ingested partitions under {root}")

    all_daily: list[pd.DataFrame] = []
    for part in parts:
        year = part.parent.name.split("=")[1]
        panel = pd.read_parquet(part)
        frames = []
        for (cid, lat, lon), cell in panel.groupby(["cell_id", "lat", "lon"], sort=False):
            frames.append(
                compute_hourly_indices(cell.sort_values("ts_utc"), float(lat), float(lon))
            )
        hourly = pd.concat(frames, ignore_index=True)

        if keep_hourly:
            hdir = settings.paths.hourly_indices_dir / f"year={year}"
            hdir.mkdir(parents=True, exist_ok=True)
            hourly.to_parquet(hdir / "part.parquet", index=False, compression="zstd")

        daily = aggregate_daily(hourly)
        all_daily.append(daily)
        log.info("year %s | %s hourly rows -> %s daily rows",
                 year, f"{len(hourly):,}", f"{len(daily):,}")

    result = pd.concat(all_daily, ignore_index=True).sort_values(["cell_id", "date"])

    # Re-attach coordinates for downstream geo work.
    coords = (
        pd.read_parquet(parts[0], columns=["cell_id", "lat", "lon"])
        .drop_duplicates("cell_id")
    )
    result = result.merge(coords, on="cell_id", how="left")

    out_path = Path(out_path or settings.paths.daily_cell_parquet)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(out_path, index=False, compression="zstd")
    log.info("daily cell records -> %s | %s rows | %.1f MB",
             out_path, f"{len(result):,}", out_path.stat().st_size / 1e6)
    return result
