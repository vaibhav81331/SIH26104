"""Grid-to-ward downscaling with an urban-heat-island uplift.

The weather grid is 0.25 deg (~27 km); a municipal ward is 1-5 km across. Two
steps bridge that gap, and both are stated as a modelling layer with its own
uncertainty rather than dressed up as measurement:

1. **Spatial interpolation.** Each ward takes the inverse-distance-weighted mean
   of the four nearest in-state grid cells.
2. **Urban heat island.** Dense, built-up, low-vegetation wards run hotter than
   the surrounding grid cell, and the effect is strongest *at night*, when
   masonry and asphalt release the day's stored heat -- precisely the
   recovery-deficit window HTSI weights at 0.20.

   ::

       dT_day   = a_day   + b_day   * built_up     (degC, applied to UTCI / WBGT)
       dT_night = a_night + b_night * built_up     (degC, applied to night WBGT)

   Defaults put a dense core (built-up 0.9) at +1.7 degC by day and +3.2 degC
   at night against an edge ward (0.3) at +0.8 / +1.4 degC. Published
   nocturnal UHI intensities for Indian cities, Bhubaneswar included, are
   mostly 2-4 degC, so the defaults sit inside that range. Satellite land-surface
   temperature per ward would replace this parameterisation directly.

Ward HTSI is then recomputed from the uplifted inputs through the same scaling
functions HTSI itself uses, so the downscaled value is consistent with the index
definition rather than an ad hoc offset.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ushma.config import settings
from ushma.indices.htsi import _scale_intensity, _scale_night_relief

__all__ = ["UHIParams", "idw_weights", "uhi_deltas", "ward_htsi_offset"]


@dataclass(frozen=True)
class UHIParams:
    a_day: float = 0.30
    b_day: float = 1.55
    a_night: float = 0.50
    b_night: float = 3.00
    #: Sensitivity of daily-max WBGT to air temperature. WBGT moves by roughly
    #: half a degree per degree of air temperature at fixed dewpoint.
    wbgt_per_degc: float = 0.55


def idw_weights(ward_lat, ward_lon, cell_lat, cell_lon, k: int = 4, power: float = 2.0):
    """Indices and weights of the ``k`` nearest cells for each ward."""
    wl = np.asarray(ward_lat)[:, None]
    wo = np.asarray(ward_lon)[:, None]
    kx = np.cos(np.radians(20.5))
    d = np.hypot((np.asarray(cell_lon)[None, :] - wo) * kx, np.asarray(cell_lat)[None, :] - wl)
    idx = np.argsort(d, axis=1)[:, :k]
    dd = np.take_along_axis(d, idx, axis=1)
    w = 1.0 / np.maximum(dd, 1e-4) ** power
    return idx, w / w.sum(axis=1, keepdims=True)


def uhi_deltas(built_up: np.ndarray, p: UHIParams | None = None) -> tuple[np.ndarray, np.ndarray]:
    p = p or UHIParams()
    b = np.clip(np.asarray(built_up, dtype=float), 0.0, 1.0)
    return p.a_day + p.b_day * b, p.a_night + p.b_night * b


def ward_htsi_offset(
    utci_cell: np.ndarray,
    night_wbgt_cell: np.ndarray,
    built_up: np.ndarray,
    p: UHIParams | None = None,
) -> dict[str, np.ndarray]:
    """HTSI change from UHI, via the index's own intensity and night scalings."""
    p = p or UHIParams()
    w = settings.htsi.normalised()
    d_day, d_night = uhi_deltas(built_up, p)
    utci_w = np.asarray(utci_cell) + d_day
    night_w = np.asarray(night_wbgt_cell) + p.wbgt_per_degc * d_night
    thr = settings.htsi.night_relief_threshold_c
    di = _scale_intensity(utci_w) - _scale_intensity(np.asarray(utci_cell))
    dn = _scale_night_relief(night_w, thr) - _scale_night_relief(np.asarray(night_wbgt_cell), thr)
    return {
        "d_htsi": w["intensity"] * di + w["night_relief"] * dn,
        "utci": utci_w,
        "night_wbgt": night_w,
        "d_day": d_day,
        "d_night": d_night,
    }


def ward_cell_frame(wards: pd.DataFrame, cells: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Convenience wrapper returning (indices into ``cells``, weights) per ward."""
    return idw_weights(wards["lat"], wards["lon"], cells["lat"], cells["lon"])
