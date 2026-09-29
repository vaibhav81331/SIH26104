"""Ingest the supplied hourly NASA POWER grid into a tidy Parquet panel.

Input
-----
``nasapower_odisha/{lat}_{lon}_{year}.csv`` -- 5,279 files, ~2.0 GB, 480 grid
points on a complete 0.25 deg lattice (lat 17.50-22.25 x lon 81.50-87.25),
years 2015-2025. Columns: ``T2M, RH2M, T2MDEW, PS, WS10M, ALLSKY_SFC_SW_DWN``
indexed by a bare ``YYYYMMDDHH`` stamp.

The timestamp problem
---------------------
The stamps carry no timezone, and NASA POWER can serve hourly data in either
UTC or Local Solar Time. Getting this wrong shifts every daily maximum and every
night-time window by several hours and silently corrupts every downstream alert,
so it is *measured* here rather than assumed.

The measurement: for each grid cell, take the irradiance-weighted centroid of
the hour label over a year and compare it against the astronomically computed
solar noon for that longitude. The difference is the cell's UTC offset. Measured
across the grid this gives a tight clustering on integers::

    lon <= 82.75  ->  UTC+5     (implied 4.88 - 4.99)
    lon >= 83.00  ->  UTC+6     (implied 5.86 - 6.05)

i.e. the files are in a *local* standard time with a one-hour step partway
across the state, not UTC. The residual of ~0.05-0.12 h from the integer is the
expected tropical morning-clear / afternoon-cloud asymmetry pulling the
irradiance centroid slightly early; it is far below the 0.5 h that would make
the integer ambiguous.

The hour label denotes the *start* of its interval, so the interval midpoint is
``HH + 0.5``; this is folded into the centroid calculation.

Because the offsets are whole hours and IST is UTC+5:30, the resulting IST
timestamps land on the half hour. That is left as-is: resampling 46 M rows to
fabricate on-the-hour IST values would invent precision the source does not
have. Grouping by IST calendar day and slicing a 22:00-06:00 IST night window
both work correctly on half-hour-offset timestamps.

Output
------
``data/interim/hourly_grid/year=YYYY/part.parquet`` with columns::

    cell_id  lat  lon  ts_utc  ts_ist  T2M  RH2M  T2MDEW  PS  WS10M
    ALLSKY_SFC_SW_DWN  is_interpolated
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ushma.config import settings
from ushma.logging_setup import get_logger

log = get_logger(__name__)

FILENAME_RE = re.compile(r"^(?P<lat>-?\d+(?:\.\d+)?)_(?P<lon>-?\d+(?:\.\d+)?)_(?P<year>\d{4})\.csv$")

VALUE_COLUMNS = ["T2M", "RH2M", "T2MDEW", "PS", "WS10M", "ALLSKY_SFC_SW_DWN"]

#: NASA POWER's fill value for missing data. The supplied files appear clean,
#: but we sweep for it anyway -- a silent -999 would poison every index.
POWER_FILL_VALUE = -999.0

#: Physically admissible ranges. Violations are counted in the QC report rather
#: than dropped, so that a data problem surfaces as a number instead of as a
#: mysteriously short output.
PHYSICAL_RANGES: dict[str, tuple[float, float]] = {
    "T2M": (-20.0, 60.0),
    "RH2M": (0.0, 100.0),
    "T2MDEW": (-30.0, 45.0),
    "PS": (80.0, 110.0),          # kPa
    "WS10M": (0.0, 60.0),         # m/s
    "ALLSKY_SFC_SW_DWN": (0.0, 1400.0),  # W/m2
}


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def discover_files(root: Path | None = None) -> pd.DataFrame:
    """Index every grid CSV, parsing lat/lon/year out of the filename."""
    root = Path(root or settings.paths.nasapower_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"NASA POWER directory not found: {root}")

    rows, skipped = [], []
    for p in sorted(root.glob("*.csv")):
        m = FILENAME_RE.match(p.name)
        if not m:
            skipped.append(p.name)
            continue
        rows.append(
            {
                "path": p,
                "lat": float(m["lat"]),
                "lon": float(m["lon"]),
                "year": int(m["year"]),
            }
        )

    if skipped:
        log.warning("Ignored %d file(s) not matching {lat}_{lon}_{year}.csv: %s",
                    len(skipped), skipped[:5])
    if not rows:
        raise RuntimeError(f"No grid CSVs found under {root}")

    df = pd.DataFrame(rows)
    df["cell_id"] = _cell_ids(df["lat"], df["lon"])
    log.info("Discovered %d files | %d cells | years %d-%d",
             len(df), df["cell_id"].nunique(), df["year"].min(), df["year"].max())
    return df


def _cell_ids(lat: pd.Series, lon: pd.Series) -> pd.Series:
    """Stable integer id per (lat, lon), ordered south-west to north-east."""
    key = lat.round(4).astype(str) + "_" + lon.round(4).astype(str)
    ordered = sorted(key.unique(), key=lambda s: (float(s.split("_")[0]), float(s.split("_")[1])))
    lookup = {k: i for i, k in enumerate(ordered)}
    return key.map(lookup).astype("int16")


def find_missing_cell_years(inventory: pd.DataFrame) -> list[tuple[float, float, int]]:
    """Cell-years present in the lattice but absent from disk."""
    cells = inventory[["lat", "lon"]].drop_duplicates()
    years = sorted(inventory["year"].unique())
    have = set(zip(inventory["lat"], inventory["lon"], inventory["year"], strict=True))
    missing = [
        (r.lat, r.lon, y)
        for r in cells.itertuples(index=False)
        for y in years
        if (r.lat, r.lon, y) not in have
    ]
    return missing


# ---------------------------------------------------------------------------
# Time-standard calibration
# ---------------------------------------------------------------------------


def _solar_noon_utc(lon: float, days: np.ndarray) -> np.ndarray:
    """Astronomical solar noon in UTC hours, via the equation of time."""
    # Spencer (1971) equation of time, minutes.
    b = 2.0 * np.pi * (days - 1) / 365.0
    eot_min = 229.18 * (
        0.000075
        + 0.001868 * np.cos(b)
        - 0.032077 * np.sin(b)
        - 0.014615 * np.cos(2 * b)
        - 0.040849 * np.sin(2 * b)
    )
    return 12.0 - lon / 15.0 - eot_min / 60.0


def measure_utc_offset(path: Path, lon: float) -> float:
    """Return the fractional UTC offset implied by this file's irradiance phase.

    Compares the irradiance-weighted centroid of the (interval-midpoint) hour
    against astronomical solar noon. A clean result sits within ~0.15 h of an
    integer.
    """
    # The index column is unnamed, which makes a ``usecols`` subset fragile
    # (pandas will happily promote the wrong column to the index). These files
    # are ~400 KB, so read the whole thing and select afterwards.
    df = pd.read_csv(path, index_col=0)
    stamps = df.index.astype(str)
    hour = stamps.str[8:10].astype(int).to_numpy()
    doy = pd.to_datetime(stamps.str[:8], format="%Y%m%d").dayofyear.to_numpy()
    sw = df["ALLSKY_SFC_SW_DWN"].to_numpy(dtype=float)

    sw = np.where(~np.isfinite(sw) | (sw <= 0), 0.0, sw)
    num = np.bincount(doy, weights=sw * (hour + 0.5))
    den = np.bincount(doy, weights=sw)
    ok = den > 0
    if ok.sum() < 30:
        raise ValueError(f"{path.name}: too little daylight data to calibrate")
    centroid = float(np.median(num[ok] / den[ok]))

    noon = float(np.median(_solar_noon_utc(lon, np.arange(1, 366))))
    return centroid - noon


@dataclass
class OffsetTable:
    """Per-cell UTC offset, measured from the data."""

    offsets: dict[int, int] = field(default_factory=dict)      # cell_id -> whole hours
    residuals: dict[int, float] = field(default_factory=dict)  # cell_id -> |measured - integer|

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "offsets": {str(k): v for k, v in self.offsets.items()},
                    "residuals": {str(k): round(v, 4) for k, v in self.residuals.items()},
                },
                indent=2,
            )
        )

    @classmethod
    def from_json(cls, path: Path) -> OffsetTable:
        raw = json.loads(path.read_text())
        return cls(
            offsets={int(k): int(v) for k, v in raw["offsets"].items()},
            residuals={int(k): float(v) for k, v in raw["residuals"].items()},
        )


def calibrate_offsets(
    inventory: pd.DataFrame,
    reference_year: int | None = None,
    max_residual_h: float = 0.25,
) -> OffsetTable:
    """Measure each cell's UTC offset and assert it is unambiguously an integer.

    This is the guard that makes a future re-download in a different time
    standard fail loudly instead of silently shifting every alert.
    """
    ref = reference_year or 2020
    subset = inventory[inventory["year"] == ref]
    if subset.empty:
        ref = int(inventory["year"].mode().iloc[0])
        subset = inventory[inventory["year"] == ref]
    log.info("Calibrating UTC offsets on %d cells using year %d", len(subset), ref)

    table = OffsetTable()
    bad: list[str] = []
    for r in subset.itertuples(index=False):
        measured = measure_utc_offset(r.path, r.lon)
        nearest = int(round(measured))
        residual = abs(measured - nearest)
        table.offsets[int(r.cell_id)] = nearest
        table.residuals[int(r.cell_id)] = residual
        if residual > max_residual_h:
            bad.append(f"cell {r.cell_id} (lat {r.lat}, lon {r.lon}): "
                       f"measured {measured:+.3f} h, nearest {nearest:+d}, residual {residual:.3f}")

    if bad:
        raise AssertionError(
            "Time-standard calibration is ambiguous for "
            f"{len(bad)} cell(s); refusing to ingest.\n  " + "\n  ".join(bad[:10])
        )

    counts = pd.Series(table.offsets).value_counts().sort_index()
    log.info("UTC offsets measured: %s",
             ", ".join(f"UTC+{o}: {n} cells" for o, n in counts.items()))
    log.info("Max residual from integer: %.3f h", max(table.residuals.values()))
    return table


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_cell_year(path: Path, lat: float, lon: float, cell_id: int, utc_offset_h: int) -> pd.DataFrame:
    """Read one grid CSV into a tidy frame with real UTC and IST timestamps."""
    df = pd.read_csv(path, index_col=0)
    missing_cols = [c for c in VALUE_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"{path.name}: missing expected column(s) {missing_cols}")

    stamp = pd.to_datetime(df.index.astype(str), format="%Y%m%d%H")
    ts_utc = stamp - pd.Timedelta(hours=utc_offset_h)

    out = pd.DataFrame(
        {
            "cell_id": np.int16(cell_id),
            "lat": np.float32(lat),
            "lon": np.float32(lon),
            "ts_utc": ts_utc,
            "ts_ist": ts_utc + pd.Timedelta(hours=settings.grid.ist_utc_offset_hours),
        }
    )
    for c in VALUE_COLUMNS:
        col = df[c].to_numpy(dtype=np.float64)
        col = np.where(np.isclose(col, POWER_FILL_VALUE), np.nan, col)
        out[c] = col.astype(np.float32)

    out["is_interpolated"] = False
    return out


def qc_cell_year(frame: pd.DataFrame, path: Path, year: int) -> dict:
    """Collect quality metrics for one cell-year. Never mutates the data."""
    expected = 8784 if _is_leap(year) else 8760
    issues: dict[str, int | float | str] = {
        "file": path.name,
        "year": year,
        "cell_id": int(frame["cell_id"].iloc[0]),
        "rows": len(frame),
        "rows_expected": expected,
        "rows_delta": len(frame) - expected,
    }

    for c in VALUE_COLUMNS:
        v = frame[c].to_numpy()
        issues[f"{c}_nan"] = int(np.isnan(v).sum())
        lo, hi = PHYSICAL_RANGES[c]
        with np.errstate(invalid="ignore"):
            issues[f"{c}_out_of_range"] = int(((v < lo) | (v > hi)).sum())

    # Dewpoint above air temperature is thermodynamically impossible; a small
    # count is reanalysis rounding, a large count means something is wrong.
    with np.errstate(invalid="ignore"):
        issues["dewpoint_exceeds_temp"] = int(
            (frame["T2MDEW"].to_numpy() > frame["T2M"].to_numpy() + 0.1).sum()
        )
        # Irradiance at local solar midnight would indicate a timestamp error.
        night = (frame["ts_ist"].dt.hour >= 23) | (frame["ts_ist"].dt.hour <= 1)
        issues["irradiance_at_midnight"] = int(
            (frame.loc[night, "ALLSKY_SFC_SW_DWN"].to_numpy() > 1.0).sum()
        )
    return issues


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


# ---------------------------------------------------------------------------
# Gap filling for absent cell-years
# ---------------------------------------------------------------------------


def interpolate_missing_cell(
    lat: float,
    lon: float,
    year: int,
    inventory: pd.DataFrame,
    offsets: OffsetTable,
    n_neighbours: int = 4,
) -> pd.DataFrame | None:
    """Reconstruct an absent cell-year by inverse-distance weighting its neighbours.

    Flagged ``is_interpolated=True`` throughout so no downstream consumer can
    mistake it for observed data.
    """
    same_year = inventory[inventory["year"] == year]
    if same_year.empty:
        return None

    d = np.hypot(same_year["lat"].to_numpy() - lat, same_year["lon"].to_numpy() - lon)
    order = np.argsort(d)[:n_neighbours]
    neigh = same_year.iloc[order]
    dist = d[order]
    if len(neigh) == 0:
        return None

    w = 1.0 / np.maximum(dist, 1e-6)
    w = w / w.sum()

    frames = []
    for wi, r in zip(w, neigh.itertuples(index=False), strict=True):
        f = read_cell_year(r.path, r.lat, r.lon, int(r.cell_id), offsets.offsets[int(r.cell_id)])
        frames.append((wi, f.set_index("ts_utc")[VALUE_COLUMNS]))

    base = frames[0][1]
    stacked = sum(wi * f.reindex(base.index) for wi, f in frames)

    # This grid point exists in other years, so it already has a cell_id. Reuse
    # it -- minting a new one would split one location into two series.
    own = inventory[(inventory["lat"] == lat) & (inventory["lon"] == lon)]
    cell_id = int(own["cell_id"].iloc[0]) if not own.empty else _next_cell_id(inventory)

    out = stacked.reset_index()
    out.insert(0, "cell_id", np.int16(cell_id))
    out.insert(1, "lat", np.float32(lat))
    out.insert(2, "lon", np.float32(lon))
    out["ts_ist"] = out["ts_utc"] + pd.Timedelta(hours=settings.grid.ist_utc_offset_hours)
    out["is_interpolated"] = True
    for c in VALUE_COLUMNS:
        out[c] = out[c].astype(np.float32)

    log.warning("Interpolated missing cell-year lat=%s lon=%s year=%d from %d neighbours",
                lat, lon, year, len(neigh))
    return out[["cell_id", "lat", "lon", "ts_utc", "ts_ist", *VALUE_COLUMNS, "is_interpolated"]]


def _next_cell_id(inventory: pd.DataFrame) -> int:
    return int(inventory["cell_id"].max()) + 1


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def ingest(
    out_dir: Path | None = None,
    years: list[int] | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """Build the partitioned hourly Parquet panel. Returns the QC report."""
    settings.paths.ensure_dirs()
    out_dir = Path(out_dir or settings.paths.hourly_grid_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # The full lattice must be established *before* any year filter, otherwise a
    # cell that is absent for the requested year looks like a cell that simply
    # does not exist and its gap is never filled.
    full_inventory = discover_files()
    missing_all = find_missing_cell_years(full_inventory)

    inventory = full_inventory
    if years:
        inventory = inventory[inventory["year"].isin(years)]

    offset_path = settings.paths.interim_dir / "utc_offsets.json"
    if offset_path.exists() and not force:
        offsets = OffsetTable.from_json(offset_path)
        log.info("Loaded cached UTC offsets for %d cells", len(offsets.offsets))
    else:
        offsets = calibrate_offsets(inventory)
        offsets.to_json(offset_path)

    missing = missing_all
    if years:
        missing = [m for m in missing if m[2] in set(years)]
    if missing:
        log.warning("%d cell-year(s) absent from disk: %s", len(missing), missing[:5])

    qc_rows: list[dict] = []
    for year, grp in inventory.groupby("year", sort=True):
        part = out_dir / f"year={year}"
        marker = part / "part.parquet"
        if marker.exists() and not force:
            log.info("year %d already ingested, skipping (use force=True to rebuild)", year)
            continue

        frames = []
        for r in grp.itertuples(index=False):
            cid = int(r.cell_id)
            f = read_cell_year(r.path, r.lat, r.lon, cid, offsets.offsets[cid])
            qc_rows.append(qc_cell_year(f, r.path, year))
            frames.append(f)

        for lat, lon, y in missing:
            if y != year:
                continue
            filled = interpolate_missing_cell(lat, lon, y, inventory, offsets)
            if filled is not None:
                frames.append(filled)

        panel = pd.concat(frames, ignore_index=True)
        panel = panel.sort_values(["cell_id", "ts_utc"], kind="stable").reset_index(drop=True)

        part.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(marker, index=False, compression="zstd")
        log.info("year %d -> %s | %s rows | %.1f MB",
                 year, marker.name, f"{len(panel):,}", marker.stat().st_size / 1e6)

    report = pd.DataFrame(qc_rows)
    if not report.empty:
        rp = settings.paths.reports_dir / "ingest_qc.csv"
        report.to_csv(rp, index=False)
        log.info("QC report -> %s", rp)
        _log_qc_summary(report)
    return report


def _log_qc_summary(report: pd.DataFrame) -> None:
    bad_rows = report[report["rows_delta"] != 0]
    log.info("QC | cell-years read: %d | wrong row count: %d", len(report), len(bad_rows))
    for c in VALUE_COLUMNS:
        n_nan = int(report[f"{c}_nan"].sum())
        n_oor = int(report[f"{c}_out_of_range"].sum())
        if n_nan or n_oor:
            log.warning("QC | %-18s NaN=%s out-of-range=%s", c, f"{n_nan:,}", f"{n_oor:,}")
    for flag in ("dewpoint_exceeds_temp", "irradiance_at_midnight"):
        n = int(report[flag].sum())
        if n:
            log.warning("QC | %-22s %s", flag, f"{n:,}")


def load_hourly(years: list[int] | None = None, columns: list[str] | None = None) -> pd.DataFrame:
    """Read the ingested panel back."""
    root = settings.paths.hourly_grid_dir
    if not root.exists():
        raise FileNotFoundError(f"No ingested panel at {root}; run ingest() first.")
    parts = sorted(root.glob("year=*/part.parquet"))
    if years:
        keep = {str(y) for y in years}
        parts = [p for p in parts if p.parent.name.split("=")[1] in keep]
    if not parts:
        raise FileNotFoundError("No matching partitions found.")
    return pd.concat((pd.read_parquet(p, columns=columns) for p in parts), ignore_index=True)
