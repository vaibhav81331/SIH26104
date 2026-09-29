"""Live mode: build today's payload from a numerical weather forecast.

Pulls a 7-day hourly forecast (plus the preceding 10 days) for the 234 in-state
grid cells from Open-Meteo, then runs it through **exactly the same code** the
historical record went through -- hourly Liljegren WBGT, human-body Tmrt, UTCI,
daily aggregation, the day-of-year climatology, HTSI, UHI downscaling and the
risk model. No separate "live" implementation of any index exists, which is
what keeps training and serving consistent.

Uncertainty
-----------
A deterministic NWP run carries no spread of its own. Until an ensemble feed is
wired in, the 80% band is set to the conformally calibrated band width the
statistical forecaster achieved on held-out 2024-2025 data at the same lead
time. That is a stated approximation, marked as such in the payload
(``uncertainty: "ml-calibrated-width"``).

Usage::

    python -m ushma.live            # writes data/serve/live/latest.json

Open-Meteo is free and needs no key. Without network access the command fails
cleanly and the dashboard stays in replay mode.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import httpx
import numpy as np
import pandas as pd

from ushma.climate.climatology import attach_anomaly
from ushma.config import settings
from ushma.export import SERVE, _write, build_payload, serve_context
from ushma.forecast.model import ARTIFACT_DIR, _prob_exceed
from ushma.indices.htsi import compute_htsi
from ushma.indices.pipeline import aggregate_daily, compute_hourly_indices
from ushma.logging_setup import get_logger

log = get_logger(__name__)

API = "https://api.open-meteo.com/v1/forecast"
HOURLY = "temperature_2m,dew_point_2m,surface_pressure,wind_speed_10m,shortwave_radiation"
BATCH = 50


def fetch(cells: pd.DataFrame, past_days: int = 10, forecast_days: int = 7) -> pd.DataFrame:
    frames = []
    with httpx.Client(timeout=60) as client:
        for start in range(0, len(cells), BATCH):
            b = cells.iloc[start:start + BATCH]
            r = client.get(API, params={
                "latitude": ",".join(f"{v:.2f}" for v in b["lat"]),
                "longitude": ",".join(f"{v:.2f}" for v in b["lon"]),
                "hourly": HOURLY, "wind_speed_unit": "ms", "timezone": "GMT",
                "past_days": past_days, "forecast_days": forecast_days,
            })
            r.raise_for_status()
            payload = r.json()
            payload = payload if isinstance(payload, list) else [payload]
            for cell, loc in zip(b.itertuples(index=False), payload, strict=True):
                h = loc["hourly"]
                # Open-Meteo stamps the END of each hour for radiation (a
                # preceding-hour mean); the index pipeline expects interval
                # starts, as in the NASA POWER files.
                ts = pd.to_datetime(h["time"]) - pd.Timedelta(hours=1)
                frames.append(pd.DataFrame({
                    "cell_id": np.int16(cell.cell_id), "lat": np.float32(cell.lat), "lon": np.float32(cell.lon),
                    "ts_utc": ts, "ts_ist": ts + pd.Timedelta(hours=settings.grid.ist_utc_offset_hours),
                    "T2M": np.asarray(h["temperature_2m"], dtype=np.float32),
                    "T2MDEW": np.asarray(h["dew_point_2m"], dtype=np.float32),
                    "PS": np.asarray(h["surface_pressure"], dtype=np.float32) / 10.0,  # hPa -> kPa
                    "WS10M": np.asarray(h["wind_speed_10m"], dtype=np.float32),
                    "ALLSKY_SFC_SW_DWN": np.asarray(h["shortwave_radiation"], dtype=np.float32),
                }))
            log.info("open-meteo: %d/%d cells", min(start + BATCH, len(cells)), len(cells))
    return pd.concat(frames, ignore_index=True).dropna()


def build_live() -> dict:
    ctx = serve_context()
    cells = ctx["cells"]
    hourly = fetch(cells)

    idx = [compute_hourly_indices(g.sort_values("ts_utc"), float(g["lat"].iloc[0]), float(g["lon"].iloc[0]))
           for _, g in hourly.groupby("cell_id")]
    daily = aggregate_daily(pd.concat(idx, ignore_index=True))
    daily = daily.merge(cells[["cell_id", "lat", "lon"]], on="cell_id", how="left")
    clim = pd.read_parquet(settings.paths.climatology_parquet)
    h = compute_htsi(attach_anomaly(daily, clim, "wbgt_max"))

    today = pd.Timestamp(datetime.now(timezone.utc) + pd.Timedelta(hours=5.5)).normalize().tz_localize(None)
    meta = json.loads((ARTIFACT_DIR / "metadata.json").read_text())
    half = {int(k): v["band_width_mean"] / 2 for k, v in meta["horizons"].items()}

    cpos, ids = ctx["cpos"], ctx["cell_ids"]
    C = {k: np.full((len(ids), 6), np.nan) for k in ("q50", "q10", "q90", "pw", "pwatch", "wbgt", "utci", "night")}
    C["hist"] = np.full((len(ids), 3), np.nan)
    warn = settings.alerts.band_edges[1]
    for r in h.itertuples(index=False):
        j = cpos.get(int(r.cell_id))
        if j is None:
            continue
        k = (pd.Timestamp(r.date) - today).days
        if -3 <= k < 0:
            C["hist"][j, k + 3] = r.htsi
        elif 0 <= k <= 5:
            w = half.get(k, 0.0) if k > 0 else 0.0
            C["q50"][j, k] = r.htsi
            C["q10"][j, k] = max(r.htsi - w, 0.0)
            C["q90"][j, k] = min(r.htsi + w, 100.0)
            C["wbgt"][j, k] = r.wbgt_max
            C["utci"][j, k] = r.utci_max
            C["night"][j, k] = r.wbgt_night_min
    # NWP is deterministic, so exceedance probabilities are read off the
    # calibrated band rather than the classifiers (which need issuance-day
    # history features that a pure NWP run does not carry).
    C["pw"] = _prob_exceed(C["q10"], C["q50"], C["q90"], warn)
    C["pwatch"] = _prob_exceed(C["q10"], C["q50"], C["q90"], settings.alerts.band_edges[0])
    C["pw"][:, 0] = (C["q50"][:, 0] >= warn).astype(float)
    C["pwatch"][:, 0] = (C["q50"][:, 0] >= settings.alerts.band_edges[0]).astype(float)

    payload = build_payload(ctx, today, C, mode="live")
    payload["source"] = "Open-Meteo hourly NWP"
    payload["uncertainty"] = "ml-calibrated-width"
    payload["fetchedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write(SERVE / "live" / "latest.json", payload)
    log.info("live payload for %s -> %s", today.date(), SERVE / "live" / "latest.json")
    return payload


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Build the live USHMA payload from Open-Meteo.").parse_args(argv)
    try:
        build_live()
    except httpx.HTTPError as e:
        log.error("live fetch failed (%s); dashboard remains in replay mode", e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
