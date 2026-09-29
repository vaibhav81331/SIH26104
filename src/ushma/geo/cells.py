"""Assign weather grid cells to districts.

No district boundary polygons were supplied, so cells are assigned by a
documented approximation:

1. **Sea mask.** An approximate Odisha coastline (Gopalpur - Chilika - Puri -
   Paradip - Dhamra - Chandipur - Talsari) is interpolated by longitude; a cell
   whose centre lies south-east of it is sea and is excluded. NASA POWER returns
   values over water, and letting ocean cells into a district average would
   depress its temperatures.
2. **Size-weighted nearest centroid.** Each land cell goes to the district
   minimising distance-to-centroid divided by the district's equivalent radius.
3. **State cut-off.** Cells whose best ratio exceeds ``reach`` are treated as
   outside Odisha (Chhattisgarh, Jharkhand, Andhra Pradesh, West Bengal).

The check on the result: Odisha is ~155,700 km^2; a 0.25 deg cell at 20 N is
~725 km^2, so roughly 215 cells should survive. The result is 224-230 cells
(~163,000-167,000 km^2), with every district represented.

This is a stand-in, and it is imprecise at district edges -- a real district
boundary file replaces it without changing any downstream code, because
everything downstream consumes the ``cell_district`` table this module writes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ushma.config import settings
from ushma.geo.districts import district_table

__all__ = ["assign_cells", "COASTLINE"]

#: (lon, lat) vertices of an approximate coastline, west to east.
COASTLINE: tuple[tuple[float, float], ...] = (
    (84.40, 18.70),
    (84.91, 19.26),   # Gopalpur
    (85.45, 19.62),   # Chilika mouth
    (85.83, 19.80),   # Puri
    (86.10, 19.88),   # Konark
    (86.67, 20.26),   # Paradip
    (86.95, 20.75),   # Dhamra
    (87.03, 21.45),   # Chandipur
    (87.47, 21.60),   # Talsari
    (87.80, 21.65),
)


def _coast_lat(lon: np.ndarray) -> np.ndarray:
    xs = np.array([p[0] for p in COASTLINE])
    ys = np.array([p[1] for p in COASTLINE])
    return np.interp(lon, xs, ys, left=-90.0, right=ys[-1])


def assign_cells(cells: pd.DataFrame, reach: float = 1.2) -> pd.DataFrame:
    """Return one row per cell with its district (``ahs_code``) or NaN.

    A size-weighted Voronoi partition: each district claims cells by the ratio
    of distance-to-centroid over its equivalent radius ``sqrt(area / pi)``.
    Plain nearest-headquarters fails badly here because many HQs sit at a
    district edge -- Nuapada, a ~3,850 km^2 district, claimed 24 cells (~17,000
    km^2) of Chhattisgarh that way. A cell is outside the state when its best
    ratio exceeds ``reach``.

    ``cells`` needs ``cell_id``, ``lat``, ``lon``.
    """
    c = cells[["cell_id", "lat", "lon"]].drop_duplicates("cell_id").copy()
    lat = c["lat"].to_numpy(dtype=float)
    lon = c["lon"].to_numpy(dtype=float)

    is_sea = lat < _coast_lat(lon) - 0.02

    d = district_table()
    kx = np.cos(np.radians(20.5))
    dx = (lon[:, None] - d["c_lon"].to_numpy()[None, :]) * kx * 111.0
    dy = (lat[:, None] - d["c_lat"].to_numpy()[None, :]) * 111.0
    dist_km = np.hypot(dx, dy)
    radius_km = np.sqrt(d["area_km2"].to_numpy() / np.pi)[None, :]
    ratio = dist_km / radius_km

    best = ratio.argmin(axis=1)
    best_ratio = ratio[np.arange(len(c)), best]
    inside = (~is_sea) & (best_ratio <= reach)

    # Fill interior holes: a land cell left out while at least 5 of its 8
    # neighbours are in the state is an artefact of the circular reach, not a
    # border.
    res = 0.25
    key = {(round(a, 2), round(b, 2)): i for i, (a, b) in enumerate(zip(lat, lon))}
    for _ in range(2):
        add = []
        for i in np.where(~inside & ~is_sea)[0]:
            n_in = 0
            for da in (-res, 0, res):
                for db in (-res, 0, res):
                    if da == 0 and db == 0:
                        continue
                    j = key.get((round(lat[i] + da, 2), round(lon[i] + db, 2)))
                    if j is not None and inside[j]:
                        n_in += 1
            if n_in >= 5:
                add.append(i)
        if not add:
            break
        inside[add] = True

    c["ahs_code"] = np.where(inside, d["ahs_code"].to_numpy()[best], np.nan)
    c["district"] = np.where(inside, d["district"].to_numpy()[best], None)
    c["reach_ratio"] = best_ratio.round(3)
    c["is_sea"] = is_sea
    c["in_odisha"] = inside

    out = settings.paths.processed_dir / "cell_district.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    c.to_parquet(out, index=False)
    return c
