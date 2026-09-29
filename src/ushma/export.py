"""Export serve-ready JSON for the Node API and the dashboard.

Python owns the science and the model; Node owns serving, alerting and the UI.
This module is the contract between them. Everything the API returns is either
in these files or computed from them by the alert engine.

Layout under ``data/serve/``::

    meta.json                 provenance, band edges, replay window, model summary
    districts.json            30 districts: population, vulnerability, pillars
    wards.geojson             ward polygons + attributes (synthetic flag carried)
    cells.geojson             the 234 in-state grid cells as 0.25 deg squares
    replay/index.json         available as-of dates
    replay/<date>.json        per as-of date: D+0 observed and D+1..D+5 forecast for
                              every ward, district and cell, with bands, risk and drivers
    live/latest.json          same schema, built from a live NWP forecast (ushma.live)
    validation.json           everything the Validation tab shows
    cooling_sites.json        candidate cooling-centre sites per city

Replay
------
The record ends on 2025-12-31, so the demo replays April-June 2024 -- the
2024 pre-monsoon heat season, which falls inside the forecaster's held-out test
period. Every forecast in a replay file was produced by a model that never saw
2024 in training or calibration.

Replay and live payloads are both assembled by :func:`build_payload`, so a
ward's number is computed one way regardless of where its weather came from.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ushma import __version__
from ushma.config import settings
from ushma.forecast.model import ARTIFACT_DIR, _prob_exceed, load_training_frame, predict
from ushma.geo.districts import district_table
from ushma.geo.uhi import UHIParams, idw_weights, ward_htsi_offset
from ushma.health.risk import load_exposure_response, mri_from_rr, relative_risk
from ushma.indices.htsi import htsi_band
from ushma.logging_setup import get_logger

log = get_logger(__name__)

SERVE = settings.paths.data_dir / "serve"
REPLAY_START = pd.Timestamp("2024-04-01")
REPLAY_END = pd.Timestamp("2024-06-30")
HISTORY_DAYS = 14


def _doy(dates) -> np.ndarray:
    ts = pd.DatetimeIndex(dates)
    d = ts.dayofyear.to_numpy().copy()
    d[np.asarray(ts.is_leap_year) & (d > 59)] -= 1
    return d


def _r(x, nd=2):
    """Round for JSON, mapping NaN to None."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return x
    return None if not np.isfinite(f) else round(f, nd)


def _write(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Static layers
# ---------------------------------------------------------------------------


def export_static() -> dict:
    dt = district_table()
    vuln = pd.read_parquet(settings.paths.processed_dir / "vulnerability.parquet")
    summ = pd.read_parquet(settings.paths.processed_dir / "district_mortality_summary.parquet")
    nfhs = pd.read_parquet(settings.paths.processed_dir / "nfhs5_districts.parquet")
    d = dt.merge(vuln.drop(columns=["district"]), on="ahs_code").merge(
        summ[["ahs_code", "pop_now", "cdr_now", "rel_rate_raw", "rel_rate", "deaths_share_65plus"]], on="ahs_code"
    ).merge(nfhs.drop(columns=["nfhs_name"]), on="ahs_code", how="left", suffixes=("", "_nfhs"))

    districts = []
    for r in d.itertuples(index=False):
        districts.append({
            "id": int(r.ahs_code), "name": r.district.title(), "hq": r.hq,
            "lat": r.hq_lat, "lon": r.hq_lon, "census2011Code": int(r.census_2011_code),
            "population": int(r.pop_now), "areaKm2": int(r.area_km2),
            "vulnerability": {
                "score": _r(r.vuln_score, 3), "rank": int(r.vuln_rank), "tier": r.vuln_tier,
                "multiplier": _r(r.vuln_mult, 3), "exposure": _r(r.pillar_exposure, 3),
                "sensitivity": _r(r.pillar_sensitivity, 3), "adaptive": _r(r.pillar_adaptive, 3),
                "suppliedHvi": _r(r.hvi_score, 1),
            },
            "profile": {
                "elderlyPct": _r(r.elderly_pct, 1), "childrenPct": _r(r.children_pct, 1),
                "electricityPct": _r(r.electricity_pct, 1), "cleanFuelPct": _r(r.clean_fuel_pct, 1),
                "healthInsurancePct": _r(r.health_insurance_pct, 1), "womenLiteratePct": _r(r.women_literate_pct, 1),
                "womenHighBpPct": _r(r.women_high_bp_pct, 1), "menHighBpPct": _r(r.men_high_bp_pct, 1),
                "womenAnaemicPct": _r(r.women_anaemic_pct, 1), "healthcareTravelMin": _r(r.healthcare_travel_min, 0),
            },
            "mortality": {"cdrNow": _r(r.cdr_now, 2), "relRate": _r(r.rel_rate, 3),
                          "deathsShare65plus": _r(r.deaths_share_65plus, 3)},
        })
    _write(SERVE / "districts.json", districts)

    wards = pd.read_parquet(settings.paths.processed_dir / "wards.parquet")
    feats = []
    for r in wards.itertuples(index=False):
        feats.append({
            "type": "Feature",
            "geometry": json.loads(r.geometry),
            "properties": {
                "id": r.ward_id, "name": r.ward_name, "city": r.city, "ulb": r.ulb_name,
                "district": int(r.ahs_code), "districtName": str(r.district).title(),
                "lat": _r(r.lat, 5), "lon": _r(r.lon, 5), "population": int(r.population),
                "elderlyPct": _r(r.elderly_pct, 1), "slumPct": _r(r.slum_pop_pct, 1),
                "builtUp": _r(r.built_up_frac, 3), "ndvi": _r(r.ndvi, 3), "areaKm2": _r(r.area_km2, 2),
                "vulnScore": _r(r.vuln_score, 3), "vulnMult": _r(r.vuln_mult, 3), "synthetic": bool(r.synthetic),
            },
        })
    _write(SERVE / "wards.geojson", {"type": "FeatureCollection", "features": feats})

    cells = pd.read_parquet(settings.paths.processed_dir / "cell_district.parquet")
    cells = cells[cells["in_odisha"]]
    half = settings.grid.resolution_deg / 2
    cf = []
    for r in cells.itertuples(index=False):
        la, lo = float(r.lat), float(r.lon)
        ring = [[lo - half, la - half], [lo + half, la - half], [lo + half, la + half],
                [lo - half, la + half], [lo - half, la - half]]
        cf.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                   "properties": {"id": int(r.cell_id), "lat": la, "lon": lo, "district": int(r.ahs_code)}})
    _write(SERVE / "cells.geojson", {"type": "FeatureCollection", "features": cf})

    sites = []
    for city, g in wards.groupby("city"):
        sites.append({"city": city, "sites": [
            {"wardId": r.ward_id, "lat": _r(r.lat, 5), "lon": _r(r.lon, 5), "population": int(r.population),
             "vulnMult": _r(r.vuln_mult, 3), "elderlyPct": _r(r.elderly_pct, 1)}
            for r in g.itertuples(index=False)]})
    _write(SERVE / "cooling_sites.json", sites)
    return {"districts": len(districts), "wards": len(feats), "cells": len(cf)}


# ---------------------------------------------------------------------------
# Payload assembly (shared by replay and live)
# ---------------------------------------------------------------------------


def serve_context() -> dict:
    """Everything a payload needs that does not change between issuance dates."""
    cells = pd.read_parquet(settings.paths.processed_dir / "cell_district.parquet")
    cells = cells[cells["in_odisha"]].reset_index(drop=True)
    wards = pd.read_parquet(settings.paths.processed_dir / "wards.parquet")
    widx, wwt = idw_weights(wards["lat"], wards["lon"], cells["lat"], cells["lon"])
    base = pd.read_parquet(settings.paths.processed_dir / "baseline_mortality.parquet")
    rate = base.assign(rate=base["expected_deaths"] / base["pop_now"]).pivot(
        index="ahs_code", columns="doy", values="rate")
    vuln = pd.read_parquet(settings.paths.processed_dir / "vulnerability.parquet").set_index("ahs_code")
    summ = pd.read_parquet(settings.paths.processed_dir / "district_mortality_summary.parquet").set_index("ahs_code")
    cell_ids = cells["cell_id"].to_numpy()
    cpos = {int(c): i for i, c in enumerate(cell_ids)}
    return {
        "er": load_exposure_response(), "uhi": UHIParams(), "cells": cells, "cell_ids": cell_ids, "cpos": cpos,
        "wards": wards, "widx": widx, "wwt": wwt, "rate": rate, "vuln": vuln, "summ": summ,
        "district_cells": {int(k): np.array([cpos[int(c)] for c in g["cell_id"]])
                           for k, g in cells.groupby("ahs_code")},
    }


def build_payload(ctx: dict, t: pd.Timestamp, C: dict, drivers_for=None, cell_observed=None,
                  mode: str = "replay") -> dict:
    """Assemble one as-of payload from per-cell arrays over [D0, D1..D5].

    ``C`` holds ``(n_cells, 6)`` arrays ``q50, q10, q90, pw, wbgt, utci, night``
    and ``hist`` of shape ``(n_cells, 3)`` -- the three observed days before
    ``t``, needed by the distributed-lag risk term.
    """
    er, uhi = ctx["er"], ctx["uhi"]
    wards, widx, wwt = ctx["wards"], ctx["widx"], ctx["wwt"]
    cell_ids = ctx["cell_ids"]
    warn = settings.alerts.band_edges[1]
    days = [t + pd.Timedelta(days=k) for k in range(6)]
    doys = _doy(days)

    def idw(a):
        return (a[widx] * wwt[:, :, None]).sum(axis=1)

    w_q50, w_q10, w_q90 = idw(C["q50"]), idw(C["q10"]), idw(C["q90"])
    w_utci, w_night, w_wbgt = idw(C["utci"]), idw(C["night"]), idw(C["wbgt"])
    w_hist = (C["hist"][widx] * wwt[:, :, None]).sum(axis=1)
    built = wards["built_up_frac"].to_numpy()
    off = ward_htsi_offset(w_utci, w_night, built[:, None], uhi)
    w_q50 = np.clip(w_q50 + off["d_htsi"], 0, 100)
    w_q10 = np.clip(w_q10 + off["d_htsi"], 0, 100)
    w_q90 = np.clip(w_q90 + off["d_htsi"], 0, 100)
    # Exceedance probabilities come from the cell classifiers, interpolated.
    # They are not shifted for the urban heat island, which makes them
    # conservative for dense core wards.
    w_pw = np.clip(idw(C["pw"]), 0, 1)
    w_pwatch = np.clip(idw(C["pwatch"]), 0, 1)
    w_pw[:, 0] = (w_q50[:, 0] >= warn).astype(float)
    w_pwatch[:, 0] = (w_q50[:, 0] >= settings.alerts.band_edges[0]).astype(float)
    w_wbgt_u = w_wbgt + uhi.wbgt_per_degc * off["d_day"]
    series = np.concatenate([w_hist + off["d_htsi"][:, :1], w_q50], axis=1)

    # Risk, vectorised over wards x leads. Lag l for lead k sits at 3 + k - l.
    lags = np.stack([series[:, 3 + k - np.arange(4)] for k in range(6)], axis=1)
    n_w = len(wards)
    vm = np.repeat(wards["vuln_mult"].to_numpy(), 6)
    flat = lags.reshape(n_w * 6, 4)
    rr = relative_risk(flat, vm, er).reshape(n_w, 6)
    rr_lo = relative_risk(flat, vm, er, "low").reshape(n_w, 6)
    rr_hi = relative_risk(flat, vm, er, "high").reshape(n_w, 6)
    br = ctx["rate"].loc[wards["ahs_code"].to_numpy(), list(doys)].to_numpy()
    exp_d = br * wards["population"].to_numpy()[:, None]
    mri = mri_from_rr(rr, er)
    bands = htsi_band(w_q50)

    ward_out = {}
    for i, wid in enumerate(wards["ward_id"]):
        recs = [{
            "date": days[k].strftime("%Y-%m-%d"), "lead": k, "observed": k == 0,
            "htsi": _r(w_q50[i, k], 1), "q10": _r(w_q10[i, k], 1), "q90": _r(w_q90[i, k], 1),
            "pWarning": _r(w_pw[i, k], 3), "pWatch": _r(w_pwatch[i, k], 3), "band": str(bands[i, k]),
            "wbgt": _r(w_wbgt_u[i, k], 1), "utci": _r(off["utci"][i, k], 1),
            "nightWbgt": _r(off["night_wbgt"][i, k], 1), "uhi": _r(off["d_htsi"][i, k], 2),
            "rr": _r(rr[i, k], 4), "mri": _r(mri[i, k], 1),
            "expectedDeaths": _r(exp_d[i, k], 4), "excessDeaths": _r(exp_d[i, k] * (rr[i, k] - 1), 4),
            "excessLow": _r(exp_d[i, k] * (rr_lo[i, k] - 1), 4),
            "excessHigh": _r(exp_d[i, k] * (rr_hi[i, k] - 1), 4),
            "edSurge": _r(exp_d[i, k] * (rr[i, k] - 1) * settings.risk.ed_per_excess_death, 3),
        } for k in range(6)]
        dom = int(cell_ids[widx[i, np.argmax(wwt[i])]])
        drivers = {str(h): (drivers_for(dom, h) if drivers_for else None) for h in (1, 3, 5)}
        ward_out[wid] = {"days": recs, "drivers": drivers, "cell": dom}

    dist_out = {}
    for code, idx in ctx["district_cells"].items():
        dq50 = np.nanmean(C["q50"][idx], axis=0)
        dq10 = np.nanmean(C["q10"][idx], axis=0)
        dq90 = np.nanmean(C["q90"][idx], axis=0)
        ser = np.concatenate([np.nanmean(C["hist"][idx], axis=0), dq50])
        dl = np.stack([ser[3 + k - np.arange(4)] for k in range(6)])
        vmd = float(ctx["vuln"].loc[code, "vuln_mult"])
        pop = float(ctx["summ"].loc[code, "pop_now"])
        drr = relative_risk(dl, vmd, er)
        drl = relative_risk(dl, vmd, er, "low")
        drh = relative_risk(dl, vmd, er, "high")
        e = ctx["rate"].loc[code, list(doys)].to_numpy() * pop
        db = htsi_band(dq50)
        dm = mri_from_rr(drr, er)
        dist_out[str(code)] = {"days": [{
            "date": days[k].strftime("%Y-%m-%d"), "lead": k, "observed": k == 0,
            "htsi": _r(dq50[k], 1), "q10": _r(dq10[k], 1), "q90": _r(dq90[k], 1),
            "htsiMax": _r(np.nanmax(C["q50"][idx, k]), 1), "band": str(db[k]),
            "pWarning": _r(float(np.nanmean(C["pw"][idx, k])), 3),
            "pWatch": _r(float(np.nanmean(C["pwatch"][idx, k])), 3),
            "wbgt": _r(np.nanmean(C["wbgt"][idx, k]), 1), "utci": _r(np.nanmean(C["utci"][idx, k]), 1),
            "rr": _r(drr[k], 4), "mri": _r(dm[k], 1),
            "expectedDeaths": _r(e[k], 2), "excessDeaths": _r(e[k] * (drr[k] - 1), 3),
            "excessLow": _r(e[k] * (drl[k] - 1), 3), "excessHigh": _r(e[k] * (drh[k] - 1), 3),
        } for k in range(6)]}

    return {
        "asOf": t.strftime("%Y-%m-%d"), "mode": mode,
        "days": [d.strftime("%Y-%m-%d") for d in days],
        "wards": ward_out, "districts": dist_out,
        "cells": {str(int(cell_ids[j])): [_r(C["q50"][j, k], 1) for k in range(6)] for j in range(len(cell_ids))},
        "cellObserved": cell_observed or {},
    }


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def export_replay() -> list[str]:
    ctx = serve_context()
    cell_ids, cpos = ctx["cell_ids"], ctx["cpos"]
    df = load_training_frame()
    issue = pd.date_range(REPLAY_START, REPLAY_END, freq="D")
    log.info("replay: forecasting %d issuance dates x %d cells", len(issue), len(cell_ids))
    # Prediction with SHAP for 91 dates x 234 cells x 5 leads is the slow step
    # (~45 min); cache it against the model files so a re-export is minutes.
    cache = ARTIFACT_DIR / "replay_predictions.pkl"
    stamp = max(p.stat().st_mtime for p in ARTIFACT_DIR.glob("h*_*.txt"))
    if cache.exists() and cache.stat().st_mtime > stamp:
        fc = pd.read_pickle(cache)
        log.info("replay: using cached predictions %s", cache.name)
    else:
        fc = predict(df, list(issue), explain=True)
        fc.to_pickle(cache)
    fc = fc[fc["cell_id"].isin(cpos.keys())].copy()
    fc["_c"] = fc["cell_id"].map(cpos).astype(int)
    shap_by = {(int(r.cell_id), r.date, int(r.horizon)): r.drivers
               for r in fc[["cell_id", "date", "horizon", "drivers"]].itertuples(index=False)}

    obs = pd.read_parquet(settings.paths.processed_dir / "daily_htsi.parquet",
                          columns=["cell_id", "date", "htsi", "wbgt_max", "utci_max", "wbgt_night_min", "t2m_max",
                                   "htsi_intensity", "htsi_anomaly", "htsi_night", "htsi_duration"])
    obs = obs[obs["cell_id"].isin(cpos.keys()) & (obs["date"] >= REPLAY_START - pd.Timedelta(days=HISTORY_DAYS))
              & (obs["date"] <= REPLAY_END)]
    dates_all = pd.date_range(obs["date"].min(), obs["date"].max(), freq="D")
    dpos = {d: i for i, d in enumerate(dates_all)}

    def cube(col):
        a = np.full((len(cell_ids), len(dates_all)), np.nan)
        a[obs["cell_id"].map(cpos).to_numpy(), obs["date"].map(dpos).to_numpy()] = obs[col].to_numpy()
        return a

    O = {c: cube(c) for c in ("htsi", "wbgt_max", "utci_max", "wbgt_night_min", "t2m_max",
                              "htsi_intensity", "htsi_anomaly", "htsi_night", "htsi_duration")}
    warn = settings.alerts.band_edges[1]
    fc_src = (("q50", "htsi_q50"), ("q10", "htsi_q10"), ("q90", "htsi_q90"), ("pw", "p_warning"), ("pwatch", "p_watch"),
              ("wbgt", "wbgt_max"), ("utci", "utci_max"), ("night", "wbgt_night_min"))
    obs_src = (("q50", "htsi"), ("q10", "htsi"), ("q90", "htsi"), ("wbgt", "wbgt_max"),
               ("utci", "utci_max"), ("night", "wbgt_night_min"))

    out_dates = []
    for t in issue:
        ti = dpos[t]
        sub = fc[fc["date"] == t]
        C = {k: np.full((len(cell_ids), 6), np.nan) for k in ("q50", "q10", "q90", "pw", "pwatch", "wbgt", "utci", "night")}
        for k, src in obs_src:
            C[k][:, 0] = O[src][:, ti]
        C["pw"][:, 0] = (O["htsi"][:, ti] >= warn).astype(float)
        C["pwatch"][:, 0] = (O["htsi"][:, ti] >= settings.alerts.band_edges[0]).astype(float)
        for h in settings.forecast.horizons:
            f = sub[sub["horizon"] == h]
            j = f["_c"].to_numpy()
            for k, src in fc_src:
                C[k][j, h] = f[src].to_numpy()
        C["hist"] = O["htsi"][:, ti - 3:ti]
        cell_obs = {
            str(int(cell_ids[j])): {
                "components": {c: _r(O[f"htsi_{c}"][j, ti], 1) for c in ("intensity", "anomaly", "night", "duration")},
                "tmax": _r(O["t2m_max"][j, ti], 1),
            } for j in range(len(cell_ids))
        }
        payload = build_payload(ctx, t, C, drivers_for=lambda c, h, _t=t: shap_by.get((c, _t, h)),
                                cell_observed=cell_obs)
        _write(SERVE / "replay" / f"{t:%Y-%m-%d}.json", payload)
        out_dates.append(t.strftime("%Y-%m-%d"))

    _write(SERVE / "replay" / "index.json", {"dates": out_dates, "default": _default_date(out_dates)})
    log.info("replay: wrote %d as-of files", len(out_dates))
    return out_dates


def _default_date(dates: list[str]) -> str:
    """Open the demo on the issuance date whose D+3 statewide risk is highest."""
    best, best_v = dates[0], -1.0
    for d in dates:
        p = json.loads((SERVE / "replay" / f"{d}.json").read_text(encoding="utf-8"))
        v = sum((x["days"][3]["excessDeaths"] or 0) for x in p["districts"].values())
        if v > best_v:
            best, best_v = d, v
    return best


# ---------------------------------------------------------------------------
# Validation bundle
# ---------------------------------------------------------------------------


def export_validation() -> dict:
    from ushma.health.district_risk import annual_summary

    meta = json.loads((ARTIFACT_DIR / "metadata.json").read_text())
    h = pd.read_parquet(settings.paths.processed_dir / "daily_htsi.parquet",
                        columns=["cell_id", "date", "htsi", "htsi_band", "t2m_max", "wbgt_max"])
    cells = pd.read_parquet(settings.paths.processed_dir / "cell_district.parquet")
    h = h.merge(cells[cells["in_odisha"]][["cell_id"]], on="cell_id")
    h = h[(h["date"] >= "2015-01-01") & (h["date"] <= "2025-12-31")]
    h["imd"] = h["t2m_max"] >= 40.0
    h["ushma"] = h["htsi_band"].isin(["Warning", "Emergency"])
    h["m"] = h["date"].dt.month
    monthly = h.groupby("m").agg(imd=("imd", "mean"), ushma=("ushma", "mean")).mul(100).round(2)

    miss = h[h["ushma"] & ~h["imd"]]
    over = h[h["imd"] & ~h["ushma"]]
    summer = h[h["m"].isin([3, 4, 5, 6])]
    jja = h[h["m"].isin([7, 8])]

    risk = pd.read_parquet(settings.paths.processed_dir / "district_risk_daily.parquet")
    ann = annual_summary(risk).reset_index()
    risk["m"] = pd.DatetimeIndex(risk["date"]).month
    by_month = risk.groupby("m")["excess_deaths"].sum().round(0)

    vul = pd.read_parquet(settings.paths.processed_dir / "vulnerability.parquet")
    rho = vul[["vuln_equal", "vuln_expert", "vuln_pca", "hvi_score"]].corr(method="spearman").round(3)

    bundle = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "forecast": meta,
        "alerts": {
            "cellDays": int(len(h)),
            "rateImdPct": round(100 * h["imd"].mean(), 2),
            "rateUshmaPct": round(100 * h["ushma"].mean(), 2),
            "ushmaMissedByTempPct": round(100 * len(miss) / max(int(h["ushma"].sum()), 1), 1),
            "tempAlertsNotUshmaPct": round(100 * len(over) / max(int(h["imd"].sum()), 1), 1),
            "missedMeanTmax": round(float(miss["t2m_max"].mean()), 1),
            "missedMeanWbgt": round(float(miss["wbgt_max"].mean()), 1),
            "overMeanWbgt": round(float(over["wbgt_max"].mean()), 1),
            "julAugImd": int(jja["imd"].sum()),
            "julAugUshma": int(jja["ushma"].sum()),
            "summerBandSharesPct": (summer["htsi_band"].value_counts(normalize=True) * 100).round(2).to_dict(),
            "monthly": [{"month": int(m), "imd": float(r.imd), "ushma": float(r.ushma)} for m, r in monthly.iterrows()],
            "notebookRedDaysPct": 49.7,
        },
        "risk": {
            "annual": [{k: (_r(v, 1) if isinstance(v, (float, np.floating)) else v) for k, v in r.items()}
                       for r in ann.to_dict("records")],
            "byMonth": {int(k): float(v) for k, v in by_month.items()},
            "ncrb": {"year": 2023, "heatstroke": 73},
        },
        "vulnerability": {"spearman": rho.to_dict()},
        "bands": {"edges": list(settings.alerts.band_edges), "weights": settings.htsi.normalised()},
    }
    _write(SERVE / "validation.json", bundle)
    return bundle


def export_meta(counts: dict, dates: list[str]) -> None:
    er = load_exposure_response()
    wards = pd.read_parquet(settings.paths.processed_dir / "wards.parquet")
    _write(SERVE / "meta.json", {
        "name": "USHMA", "version": __version__,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "replay", "replay": {"start": dates[0], "end": dates[-1]},
        "record": {"start": "2015-01-01", "end": "2025-12-31", "source": "NASA POWER hourly, 480 cells, 0.25 deg"},
        "counts": counts,
        "bands": {"names": ["Normal", "Watch", "Warning", "Emergency"], "edges": list(settings.alerts.band_edges)},
        "htsiWeights": settings.htsi.normalised(),
        "exposureResponse": {"threshold": er.threshold, "referenceHtsi": er.reference_htsi,
                             "rrAtReference": [er.rr_ref_low, er.rr_ref, er.rr_ref_high],
                             "lagWeights": list(er.lag_weights)},
        "syntheticWards": bool(wards["synthetic"].all()),
        "exceedance": {h: {lvl: {"threshold": v["threshold"], "auc": v["auc"], "f1": v["model"]["f1"]}
                           for lvl, v in r.items()}
                       for h, r in json.loads((ARTIFACT_DIR / "metadata.json").read_text()).get("exceedance", {}).items()},
        "notes": [
            "Heat exposure-response is transferred from literature; mortality and weather records share no days.",
            "Ward geometry is synthetic until real boundaries are supplied at data/geo/wards.geojson.",
            "Replay forecasts come from a model whose training and calibration ended 2023-12-31.",
        ],
    })


def export_all() -> None:
    if SERVE.exists():
        live = SERVE / "live"
        keep = live.exists()
        if keep:
            shutil.move(str(live), str(settings.paths.data_dir / "_live_keep"))
        shutil.rmtree(SERVE)
        if keep:
            SERVE.mkdir(parents=True)
            shutil.move(str(settings.paths.data_dir / "_live_keep"), str(live))
    counts = export_static()
    dates = export_replay()
    export_validation()
    export_meta(counts, dates)
    log.info("serve bundle -> %s", SERVE)


if __name__ == "__main__":
    export_all()
