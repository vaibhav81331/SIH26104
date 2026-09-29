"""Mortality Risk Index: thermal stress -> expected excess deaths.

The risk model is a transparent product of named terms, every one of which is
either estimated from the supplied data or read from a cited file::

    excess(w, t) = base_rate(d, doy)       fitted  AHS 2007-11 (de-duplicated)
                 * population(w)           local   Census 2011, scaled
                 * [ RR_ward(w, t) - 1 ]

    log RR_ward  = vuln_mult(w) * log RR_eff(t)       vuln_mult  fitted  HVI + NFHS-5
    log RR_eff   = sum_l lag_w[l] * beta * max(HTSI[t-l] - h0, 0)
                                                     beta, h0, lag_w  TRANSFERRED

Vulnerability modifies risk on the log scale (effect modification), so a ward
twice as vulnerable does not simply double its deaths: it raises the exponent.

No machine learning happens here, by design. The learned component of USHMA is
the HTSI forecaster upstream; this stage turns its output into numbers a
health department uses -- excess deaths, attributable fraction, expected
emergency-department surge -- and every one of them can be decomposed on screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ushma.config import settings

__all__ = ["ExposureResponse", "load_exposure_response", "relative_risk", "excess_deaths"]

_DEFAULT_YAML = settings.paths.project_root / "config" / "exposure_response.yaml"


@dataclass(frozen=True)
class ExposureResponse:
    threshold: float
    reference_htsi: float
    rr_ref: float
    rr_ref_low: float
    rr_ref_high: float
    lag_weights: tuple[float, ...]
    max_rr: float
    mri_reference_excess: float

    def beta(self, which: str = "central") -> float:
        rr = {"central": self.rr_ref, "low": self.rr_ref_low, "high": self.rr_ref_high}[which]
        return float(np.log(rr) / max(self.reference_htsi - self.threshold, 1e-6))


def load_exposure_response(path: Path | None = None) -> ExposureResponse:
    cfg = yaml.safe_load(Path(path or _DEFAULT_YAML).read_text(encoding="utf-8"))
    lw = np.asarray(cfg["lag_weights"]["values"], dtype=float)
    if abs(lw.sum() - 1.0) > 1e-6:
        raise ValueError(f"lag weights must sum to 1, got {lw.sum():.4f}")
    rr = cfg["relative_risk_at_reference"]
    return ExposureResponse(
        threshold=float(cfg["threshold"]["value"]),
        reference_htsi=float(cfg["reference_point"]["htsi"]),
        rr_ref=float(rr["central"]),
        rr_ref_low=float(rr["low"]),
        rr_ref_high=float(rr["high"]),
        lag_weights=tuple(lw.tolist()),
        max_rr=float(cfg["max_relative_risk"]["value"]),
        mri_reference_excess=float(cfg["mri_reference_excess"]["value"]),
    )


def log_rr_eff(htsi_lags: np.ndarray, er: ExposureResponse, which: str = "central") -> np.ndarray:
    """Distributed-lag log relative risk.

    ``htsi_lags`` has shape ``(n, L)`` with column ``l`` holding HTSI at lag ``l``
    (column 0 is today). Missing lags count as no excess exposure.
    """
    h = np.nan_to_num(np.asarray(htsi_lags, dtype=float), nan=0.0)
    w = np.asarray(er.lag_weights)[: h.shape[1]]
    excess = np.maximum(h - er.threshold, 0.0)
    out = er.beta(which) * (excess * w[None, :]).sum(axis=1)
    return np.minimum(out, np.log(er.max_rr))


def relative_risk(htsi_lags: np.ndarray, vuln_mult: np.ndarray | float,
                  er: ExposureResponse, which: str = "central") -> np.ndarray:
    """Ward relative risk after vulnerability effect-modification."""
    return np.exp(np.asarray(vuln_mult, dtype=float) * log_rr_eff(htsi_lags, er, which))


def mri_from_rr(rr: np.ndarray, er: ExposureResponse) -> np.ndarray:
    """Map relative risk onto the 0-100 Mortality Risk Index."""
    return np.clip(100.0 * (np.asarray(rr) - 1.0) / er.mri_reference_excess, 0.0, 100.0)


def lag_matrix(series: pd.Series, n_lags: int, by: pd.Series | None = None) -> np.ndarray:
    """Stack lags 0..n_lags-1 of a series, optionally within groups."""
    cols = []
    for lag in range(n_lags):
        cols.append((series.groupby(by).shift(lag) if by is not None else series.shift(lag)).to_numpy())
    return np.column_stack(cols)


def excess_deaths(
    frame: pd.DataFrame,
    htsi_lags: np.ndarray,
    er: ExposureResponse | None = None,
) -> pd.DataFrame:
    """Add RR, MRI, excess deaths and ED surge (central and interval) to ``frame``.

    ``frame`` needs ``base_rate`` (deaths per person per day), ``population`` and
    ``vuln_mult``, aligned row-for-row with ``htsi_lags``.
    """
    er = er or load_exposure_response()
    base = frame["base_rate"].to_numpy(dtype=float) * frame["population"].to_numpy(dtype=float)
    vm = frame["vuln_mult"].to_numpy(dtype=float)
    out = frame.copy()
    for which in ("central", "low", "high"):
        rr = relative_risk(htsi_lags, vm, er, which)
        suffix = "" if which == "central" else f"_{which}"
        out[f"rr{suffix}"] = rr.astype(np.float32)
        out[f"excess_deaths{suffix}"] = (base * (rr - 1.0)).astype(np.float32)
    out["expected_deaths"] = base.astype(np.float32)
    out["mri"] = mri_from_rr(out["rr"].to_numpy(), er).astype(np.float32)
    cfg = settings.risk
    out["ed_surge"] = (out["excess_deaths"] * cfg.ed_per_excess_death).astype(np.float32)
    out["ed_surge_low"] = (out["excess_deaths_low"] * cfg.ed_per_excess_death_low).astype(np.float32)
    out["ed_surge_high"] = (out["excess_deaths_high"] * cfg.ed_per_excess_death_high).astype(np.float32)
    return out
