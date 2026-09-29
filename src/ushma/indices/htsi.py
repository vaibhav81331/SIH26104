"""The Human Thermal Stress Index.

The problem statement asks for "a comprehensive Human Thermal Stress Index
(integrating temperature, humidity, wind, and radiation)". A single named index
does not satisfy "comprehensive", and an undefined blend is not defensible. HTSI
is therefore a 0-100 composite of four physiologically distinct channels, each
independently grounded in the heat-health literature.

============  ======  =========================================================
Component     Weight  What it captures
============  ======  =========================================================
Intensity     0.40    Peak physiological load -- daily-max UTCI on its official
                      stress bands, cross-checked against Liljegren WBGT.
Anomaly       0.25    How unusual this is *here*. Acclimatisation means the same
                      42 degC is not the same risk in Bolangir and Balasore.
Night relief  0.20    Shortfall of the overnight index minimum below the
                      recovery threshold. Failure of overnight recovery is among
                      the strongest mortality predictors and is invisible to
                      every daytime-maximum warning in use.
Duration      0.15    Consecutive days above the 90th percentile, saturating.
                      Cumulative strain depletes coping capacity.
============  ======  =========================================================

Weights live in ``config.py``, not here. ``docs/04_HTSI_SPEC.md`` carries the
sensitivity analysis, because the first question anyone should ask about a
composite index is where its weights came from, and the right answer is a table
rather than a shrug.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ushma.config import settings

__all__ = ["compute_htsi", "htsi_band", "HTSI_BANDS"]

#: HTSI alert bands. Edges come from ``settings.alerts.band_edges`` so that the
#: banding and the alert state machine can never drift apart.
HTSI_BANDS: tuple[str, ...] = ("Normal", "Watch", "Warning", "Emergency")


def _scale_intensity(utci_max: np.ndarray) -> np.ndarray:
    """Map daily-max UTCI onto 0-100 using its official stress-band edges.

    Piecewise-linear through the published boundaries rather than a bare
    min-max, so that a given HTSI value keeps a fixed physiological meaning
    instead of depending on whatever range happened to be in the sample.
    """
    # UTCI band edges -> score anchors.
    edges = np.array([9.0, 26.0, 32.0, 38.0, 46.0, 55.0])
    scores = np.array([0.0, 25.0, 45.0, 65.0, 85.0, 100.0])
    return np.clip(np.interp(utci_max, edges, scores), 0.0, 100.0)


def _scale_anomaly(pct_rank: np.ndarray) -> np.ndarray:
    """Map the day-of-year percentile rank onto 0-100.

    Deliberately non-linear: the bottom 80 percent of days carry almost no
    excess risk, so the response is flat there and rises steeply through the
    tail where the epidemiology actually lives.
    """
    edges = np.array([0.0, 80.0, 90.0, 95.0, 98.0, 100.0])
    scores = np.array([0.0, 10.0, 40.0, 65.0, 85.0, 100.0])
    return np.clip(np.interp(pct_rank, edges, scores), 0.0, 100.0)


def _scale_night_relief(night_min: np.ndarray, threshold: float) -> np.ndarray:
    """Score the overnight recovery deficit.

    Zero while the night falls below the recovery threshold; rising once it does
    not. A 6 degC shortfall is treated as complete failure of recovery.
    """
    deficit = np.maximum(night_min - threshold, 0.0)
    return np.clip(deficit / 6.0 * 100.0, 0.0, 100.0)


def _scale_duration(spell_days: np.ndarray, saturation: int) -> np.ndarray:
    """Score consecutive hot days, saturating.

    The marginal effect of one more hot day falls away once a spell is
    established, so the curve is concave rather than linear.
    """
    x = np.clip(spell_days, 0, None) / max(saturation, 1)
    return np.clip(100.0 * (1.0 - np.exp(-1.6 * x)), 0.0, 100.0)


def _spell_length(df: pd.DataFrame, hot_col: str, group_col: str = "cell_id") -> np.ndarray:
    """Consecutive-day counter for a boolean 'hot' flag, per cell."""
    out = np.zeros(len(df), dtype=np.int32)
    hot = df[hot_col].to_numpy()
    groups = df[group_col].to_numpy()
    run = 0
    prev = None
    for i in range(len(df)):
        if groups[i] != prev:
            run = 0
            prev = groups[i]
        run = run + 1 if hot[i] else 0
        out[i] = run
    return out


def compute_htsi(
    daily: pd.DataFrame,
    anomaly_col: str = "wbgt_max_pct_rank",
    utci_col: str = "utci_max",
    night_col: str = "wbgt_night_min",
    hot_threshold_col: str = "wbgt_max_p90",
    value_col: str = "wbgt_max",
) -> pd.DataFrame:
    """Compute HTSI and its four components.

    Expects ``daily`` to already carry climatology columns -- run
    :func:`ushma.climate.climatology.attach_anomaly` first.
    """
    w = settings.htsi.normalised()
    df = daily.sort_values(["cell_id", "date"]).reset_index(drop=True).copy()

    missing = [c for c in (anomaly_col, utci_col, night_col) if c not in df.columns]
    if missing:
        raise KeyError(f"HTSI needs {missing}; attach climatology first")

    intensity = _scale_intensity(df[utci_col].to_numpy(dtype=np.float64))
    anomaly = _scale_anomaly(df[anomaly_col].to_numpy(dtype=np.float64))
    night = _scale_night_relief(
        np.nan_to_num(df[night_col].to_numpy(dtype=np.float64), nan=0.0),
        settings.htsi.night_relief_threshold_c,
    )

    if hot_threshold_col in df.columns:
        df["_hot"] = df[value_col].to_numpy() >= df[hot_threshold_col].to_numpy()
    else:
        # Without climatology, fall back to the anomaly rank itself.
        df["_hot"] = df[anomaly_col].to_numpy() >= 90.0
    spell = _spell_length(df, "_hot")
    duration = _scale_duration(spell, settings.htsi.duration_saturation_days)

    # Physiological gate. "Unusual for here" only matters when it is also hot.
    # Ungated, a sunny 28 degC January day with 13 degC nights -- pleasant weather
    # that is merely warm *for January* -- scored ~81 on anomaly and ~39 on
    # duration, crossed the Watch edge, and led the risk model to attribute
    # ~860 heat deaths to December-January. Gating on UTCI does not help: a person
    # standing in midday sun reaches UTCI ~34 even in winter. WBGT, the
    # occupational heat-strain standard, separates them cleanly (28.4 degC on
    # those January days versus 35.3 degC on May alert days), so anomaly and
    # duration ramp in as daily-max WBGT rises from 27 to 31 degC.
    gate = np.clip((df[value_col].to_numpy(dtype=np.float64) - 27.0) / 4.0, 0.0, 1.0)
    anomaly = anomaly * gate
    duration = duration * gate
    df["htsi_gate"] = gate.astype(np.float32)

    df["htsi_intensity"] = intensity.astype(np.float32)
    df["htsi_anomaly"] = anomaly.astype(np.float32)
    df["htsi_night"] = night.astype(np.float32)
    df["htsi_duration"] = duration.astype(np.float32)
    df["spell_days"] = spell.astype(np.int16)

    df["htsi"] = (
        w["intensity"] * intensity
        + w["anomaly"] * anomaly
        + w["night_relief"] * night
        + w["duration"] * duration
    ).astype(np.float32)

    df["htsi_band"] = htsi_band(df["htsi"].to_numpy())
    return df.drop(columns="_hot")


def htsi_band(htsi: np.ndarray) -> np.ndarray:
    """Map HTSI onto its four alert bands."""
    e1, e2, e3 = settings.alerts.band_edges
    out = np.full(np.shape(htsi), HTSI_BANDS[0], dtype=object)
    out = np.where(htsi >= e1, HTSI_BANDS[1], out)
    out = np.where(htsi >= e2, HTSI_BANDS[2], out)
    out = np.where(htsi >= e3, HTSI_BANDS[3], out)
    return out.astype(str)
