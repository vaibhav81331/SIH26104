"""The HTSI forecaster -- USHMA's trained machine-learning model.

What it predicts, and why not deaths
------------------------------------
The supplied mortality and weather records share no days, so deaths are not a
trainable label. Thermal stress is: 234 Odisha grid cells x 11 years of daily
HTSI, WBGT and UTCI derived from ~46 M hourly observations of the mandated
``nasapower_odisha`` dataset. The model forecasts thermal stress 1-5 days
ahead; the deterministic risk model in :mod:`ushma.health.risk` turns that into
excess deaths.

Design
------
* **Direct multi-horizon.** One model per lead time D+1 ... D+5, so errors do not
  compound through a recursive loop.
* **Quantile regression** (LightGBM, tau = 0.1 / 0.5 / 0.9) for HTSI, plus
  point models for daily-max WBGT, daily-max UTCI and night-min WBGT, which the
  ward downscaling and the dashboard need.
* **Split-conformal calibration** (conformalised quantile regression) on the
  2023 validation year, so the stated 80% band covers ~80% of outcomes rather
  than whatever the raw quantiles happen to deliver.
* **Strictly temporal split** -- train 2015-2022, validate 2023, test 2024-2025.
  Never random K-fold on a time series.
* **Honest baselines** -- persistence and day-of-year climatology, both scored
  on the same test rows.

Features use only information available at issuance: the issuing day's indices
and their lags, rolling statistics, the spell counter, climatological
thresholds for the *target* day (known in advance by construction), seasonal
harmonics and location. Climatological means are computed from training years
only.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ushma.config import settings
from ushma.logging_setup import get_logger

log = get_logger(__name__)

__all__ = ["build_features", "train", "train_exceedance", "load_models", "predict", "FEATURE_LABELS"]

ARTIFACT_DIR = settings.paths.artifacts_dir / "forecast"

POINT_TARGETS = ("wbgt_max", "utci_max", "wbgt_night_min")
LAG_VARS = ("htsi", "wbgt_max", "utci_max", "t2m_max", "wbgt_night_min")

#: Plain-language names for the explanation layer.
FEATURE_LABELS: dict[str, str] = {
    "htsi_l0": "today's thermal stress",
    "htsi_l1": "yesterday's thermal stress",
    "htsi_r3": "3-day mean thermal stress",
    "htsi_r7": "7-day mean thermal stress",
    "htsi_r14": "14-day mean thermal stress",
    "htsi_max7": "peak stress in the last week",
    "wbgt_max_l0": "today's peak WBGT",
    "wbgt_max_r7": "7-day mean peak WBGT",
    "utci_max_l0": "today's peak UTCI",
    "t2m_max_l0": "today's maximum temperature",
    "wbgt_night_min_l0": "last night's minimum WBGT",
    "wbgt_night_min_r3": "3-night mean minimum WBGT",
    "spell_days": "consecutive hot days so far",
    "d_htsi": "change in stress since yesterday",
    "clim_htsi_target": "normal stress for the target date",
    "clim_p90_target": "local 90th-percentile WBGT for the target date",
    "anom_today": "today's stress relative to normal",
    "doy_sin": "time of year",
    "doy_cos": "time of year",
    "lat": "latitude",
    "lon": "longitude",
}


def _doy(dates: pd.Series) -> np.ndarray:
    ts = pd.DatetimeIndex(dates)
    d = ts.dayofyear.to_numpy().copy()
    d[np.asarray(ts.is_leap_year) & (d > 59)] -= 1
    return d


def load_training_frame() -> pd.DataFrame:
    """Daily HTSI for cells inside Odisha, sorted for time-series operations."""
    cols = ["cell_id", "date", "lat", "lon", "htsi", "spell_days", "wbgt_max_p90", *[v for v in LAG_VARS if v != "htsi"]]
    h = pd.read_parquet(settings.paths.processed_dir / "daily_htsi.parquet", columns=list(dict.fromkeys(cols)))
    cells = pd.read_parquet(settings.paths.processed_dir / "cell_district.parquet")
    keep = cells.loc[cells["in_odisha"], "cell_id"]
    h = h[h["cell_id"].isin(keep)]
    h = h[(h["date"] >= "2015-01-01") & (h["date"] <= "2025-12-31")]
    return h.sort_values(["cell_id", "date"]).reset_index(drop=True)


def _climatology_means(df: pd.DataFrame, train_end: str) -> pd.DataFrame:
    """Per-cell, per-day-of-year mean HTSI from training years only."""
    tr = df[df["date"] <= train_end].assign(doy=lambda x: _doy(x["date"]))
    m = tr.groupby(["cell_id", "doy"])["htsi"].mean()
    # Smooth across day of year (circular 15-day window) to damp sampling noise.
    wide = m.unstack("doy").reindex(columns=range(1, 366))
    arr = wide.to_numpy()
    pad = np.concatenate([arr[:, -7:], arr, arr[:, :7]], axis=1)
    kernel = np.ones(15) / 15
    smooth = np.apply_along_axis(lambda r: np.convolve(np.nan_to_num(r, nan=np.nanmean(r)), kernel, "valid"), 1, pad)
    out = pd.DataFrame(smooth, index=wide.index, columns=range(1, 366)).stack().rename("clim_htsi")
    return out.reset_index().rename(columns={"level_1": "doy"})


def build_features(df: pd.DataFrame, clim: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Issuance-time features for predicting ``horizon`` days ahead."""
    g = df.groupby("cell_id", sort=False)
    X = df[["cell_id", "date", "lat", "lon", "spell_days"]].copy()

    for v in LAG_VARS:
        for lag in (0, 1, 2, 3, 6):
            X[f"{v}_l{lag}"] = g[v].shift(lag)
    for v in ("htsi", "wbgt_max", "wbgt_night_min"):
        for w in (3, 7, 14):
            X[f"{v}_r{w}"] = g[v].transform(lambda s, _w=w: s.rolling(_w, min_periods=_w).mean())
    X["htsi_max7"] = g["htsi"].transform(lambda s: s.rolling(7, min_periods=7).max())
    X["d_htsi"] = X["htsi_l0"] - X["htsi_l1"]

    # Targets are attached here, while X is still row-aligned with df and
    # before any merge can reorder it. NaN beyond the end of the record.
    for v in ("htsi", *POINT_TARGETS):
        X[f"y_{v}"] = g[v].shift(-horizon)

    target_date = X["date"] + pd.Timedelta(days=horizon)
    tdoy = _doy(target_date)
    X["doy_sin"] = np.sin(2 * np.pi * tdoy / 365.0)
    X["doy_cos"] = np.cos(2 * np.pi * tdoy / 365.0)
    X["_tdoy"] = tdoy
    X["_idoy"] = _doy(X["date"])
    X = X.merge(clim.rename(columns={"doy": "_tdoy", "clim_htsi": "clim_htsi_target"}), on=["cell_id", "_tdoy"], how="left")
    X = X.merge(clim.rename(columns={"doy": "_idoy", "clim_htsi": "_clim_today"}), on=["cell_id", "_idoy"], how="left")
    X["anom_today"] = X["htsi_l0"] - X["_clim_today"]

    p90 = df[["cell_id", "date", "wbgt_max_p90"]].rename(columns={"date": "_tdate", "wbgt_max_p90": "clim_p90_target"})
    X["_tdate"] = target_date
    X = X.merge(p90, on=["cell_id", "_tdate"], how="left")

    X["target_date"] = target_date
    return X.drop(columns=["_tdoy", "_idoy", "_clim_today", "_tdate"])


def feature_columns(X: pd.DataFrame) -> list[str]:
    return [c for c in X.columns if not c.startswith("y_") and c not in ("cell_id", "date", "target_date")]


def _lgb_params(objective: str, alpha: float | None = None) -> dict:
    p = {
        "objective": objective,
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 80,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l2": 1.0,
        "verbose": -1,
        "seed": settings.forecast.random_state,
        "num_threads": 0,
    }
    if alpha is not None:
        p["alpha"] = alpha
    return p


def _fit(Xtr, ytr, Xva, yva, params, rounds=1200) -> lgb.Booster:
    dtr = lgb.Dataset(Xtr, ytr, free_raw_data=False)
    dva = lgb.Dataset(Xva, yva, reference=dtr, free_raw_data=False)
    return lgb.train(
        params, dtr, num_boost_round=rounds, valid_sets=[dva],
        callbacks=[lgb.early_stopping(60, verbose=False)],
    )


def _prob_exceed(q10, q50, q90, thr):
    """P(Y >= thr) from three quantiles, piecewise-linear CDF with linear tails."""
    q10, q50, q90 = map(np.asarray, (q10, q50, q90))
    lo_slope = 0.4 / np.maximum(q50 - q10, 1e-3)
    hi_slope = 0.4 / np.maximum(q90 - q50, 1e-3)
    cdf = np.where(
        thr <= q50,
        0.5 - (q50 - thr) * lo_slope,
        0.5 + (thr - q50) * hi_slope,
    )
    return 1.0 - np.clip(cdf, 0.0, 1.0)


def train() -> dict:
    """Train all horizons, calibrate, evaluate against baselines, save artefacts."""
    cfg = settings.forecast
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_training_frame()
    clim = _climatology_means(df, cfg.train_end)
    clim.to_parquet(ARTIFACT_DIR / "clim_htsi.parquet", index=False)
    warn_edge = settings.alerts.band_edges[1]

    meta: dict = {"horizons": {}, "quantiles": list(cfg.quantiles), "train_end": cfg.train_end,
                  "valid_end": cfg.valid_end, "warning_edge": warn_edge}
    test_rows = []

    for h in cfg.horizons:
        t0 = time.time()
        X = build_features(df, clim, h).dropna(subset=["y_htsi", "htsi_r14", "clim_p90_target"])
        feats = feature_columns(X)
        tr = X[X["target_date"] <= cfg.train_end]
        va = X[(X["target_date"] > cfg.train_end) & (X["target_date"] <= cfg.valid_end)]
        te = X[X["target_date"] > cfg.valid_end]

        models: dict[str, lgb.Booster] = {}
        for q in cfg.quantiles:
            m = _fit(tr[feats], tr["y_htsi"], va[feats], va["y_htsi"], _lgb_params("quantile", q))
            models[f"htsi_q{int(q * 100)}"] = m
        for v in POINT_TARGETS:
            ok_tr, ok_va = tr[f"y_{v}"].notna(), va[f"y_{v}"].notna()
            models[v] = _fit(tr.loc[ok_tr, feats], tr.loc[ok_tr, f"y_{v}"],
                             va.loc[ok_va, feats], va.loc[ok_va, f"y_{v}"], _lgb_params("regression"))

        # --- conformalised quantile regression on the validation year ---
        q10v = models["htsi_q10"].predict(va[feats])
        q90v = models["htsi_q90"].predict(va[feats])
        scores = np.maximum(q10v - va["y_htsi"].to_numpy(), va["y_htsi"].to_numpy() - q90v)
        n = len(scores)
        level = min(1.0, np.ceil((n + 1) * (1 - cfg.conformal_alpha)) / n)
        qhat = float(np.quantile(scores, level))

        # --- test-set evaluation ---
        pq10 = models["htsi_q10"].predict(te[feats]) - qhat
        pq50 = models["htsi_q50"].predict(te[feats])
        pq90 = models["htsi_q90"].predict(te[feats]) + qhat
        y = te["y_htsi"].to_numpy()
        persist = te["htsi_l0"].to_numpy()
        climo = te["clim_htsi_target"].to_numpy()

        def mae(a):
            return float(np.mean(np.abs(a - y)))

        summer = te["target_date"].dt.month.isin([3, 4, 5, 6]).to_numpy()
        obs_warn = y >= warn_edge
        p_warn = _prob_exceed(pq10, pq50, pq90, warn_edge)

        def prf(pred):
            tp = int((pred & obs_warn).sum()); fp = int((pred & ~obs_warn).sum()); fn = int((~pred & obs_warn).sum())
            p = tp / max(tp + fp, 1); r = tp / max(tp + fn, 1)
            return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / max(p + r, 1e-9), 3)}

        brier = float(np.mean((p_warn - obs_warn) ** 2))
        brier_clim = float(np.mean((obs_warn.mean() - obs_warn) ** 2))

        res = {
            "n_train": int(len(tr)), "n_valid": int(len(va)), "n_test": int(len(te)),
            "conformal_qhat": round(qhat, 3),
            "mae_model": round(mae(pq50), 3),
            "mae_persistence": round(mae(persist), 3),
            "mae_climatology": round(mae(climo), 3),
            "mae_model_summer": round(float(np.mean(np.abs(pq50[summer] - y[summer]))), 3),
            "mae_persistence_summer": round(float(np.mean(np.abs(persist[summer] - y[summer]))), 3),
            "skill_vs_persistence": round(1 - mae(pq50) / mae(persist), 3),
            "skill_vs_climatology": round(1 - mae(pq50) / mae(climo), 3),
            "coverage_80_raw": round(float(np.mean((y >= pq10 + qhat) & (y <= pq90 - qhat))), 3),
            "coverage_80_conformal": round(float(np.mean((y >= pq10) & (y <= pq90))), 3),
            "band_width_mean": round(float(np.mean(pq90 - pq10)), 2),
            "warning_model": prf(pq50 >= warn_edge),
            "warning_prob50": prf(p_warn >= 0.5),
            "warning_persistence": prf(persist >= warn_edge),
            "brier_warning": round(brier, 4),
            "brier_skill_vs_base_rate": round(1 - brier / max(brier_clim, 1e-12), 3),
            "best_iterations": {k: int(m.best_iteration or m.current_iteration()) for k, m in models.items()},
            "seconds": round(time.time() - t0, 1),
        }
        # reliability curve for P(Warning+)
        bins = np.linspace(0, 1, 11)
        idx = np.clip(np.digitize(p_warn, bins) - 1, 0, 9)
        res["reliability"] = [
            {"bin": round(float((bins[i] + bins[i + 1]) / 2), 2), "n": int((idx == i).sum()),
             "observed": round(float(obs_warn[idx == i].mean()), 3) if (idx == i).any() else None}
            for i in range(10)
        ]
        meta["horizons"][str(h)] = res
        meta["features"] = feats

        for k, m in models.items():
            m.save_model(str(ARTIFACT_DIR / f"h{h}_{k}.txt"))
        log.info("D+%d | MAE model %.2f vs persistence %.2f vs climatology %.2f | cover80 %.3f | F1 warn %.2f (persist %.2f) | %.0fs",
                 h, res["mae_model"], res["mae_persistence"], res["mae_climatology"], res["coverage_80_conformal"],
                 res["warning_model"]["f1"], res["warning_persistence"]["f1"], res["seconds"])

        if h in (1, 3):
            test_rows.append(te.assign(horizon=h))

    # --- SHAP global importance on the median models ---
    import shap
    meta["shap"] = {}
    for sample in test_rows:
        h = int(sample["horizon"].iloc[0])
        s = sample.sample(n=min(4000, len(sample)), random_state=cfg.random_state)
        booster = lgb.Booster(model_file=str(ARTIFACT_DIR / f"h{h}_htsi_q50.txt"))
        sv = shap.TreeExplainer(booster).shap_values(s[feats])
        imp = np.abs(sv).mean(axis=0)
        order = np.argsort(imp)[::-1]
        meta["shap"][str(h)] = [
            {"feature": feats[i], "label": FEATURE_LABELS.get(feats[i], feats[i]), "mean_abs_shap": round(float(imp[i]), 3)}
            for i in order[:15]
        ]

    (ARTIFACT_DIR / "metadata.json").write_text(json.dumps(meta, indent=2))
    log.info("forecast artefacts -> %s", ARTIFACT_DIR)
    return meta


def load_models() -> tuple[dict[int, dict[str, lgb.Booster]], dict]:
    meta = json.loads((ARTIFACT_DIR / "metadata.json").read_text())
    models = {}
    for h in settings.forecast.horizons:
        models[h] = {
            p.stem.split("_", 1)[1]: lgb.Booster(model_file=str(p))
            for p in ARTIFACT_DIR.glob(f"h{h}_*.txt")
        }
    return models, meta


def predict(df: pd.DataFrame, issue_dates: list[pd.Timestamp], explain: bool = False) -> pd.DataFrame:
    """Forecast D+1..D+5 from each issuance date, with calibrated bands."""
    models, meta = load_models()
    clim = pd.read_parquet(ARTIFACT_DIR / "clim_htsi.parquet")
    feats = meta["features"]
    warn = meta["warning_edge"]
    issue_dates = pd.DatetimeIndex(issue_dates)
    out = []
    for h, ms in models.items():
        X = build_features(df, clim, h)
        X = X[X["date"].isin(issue_dates)]
        qhat = meta["horizons"][str(h)]["conformal_qhat"]
        r = X[["cell_id", "date", "target_date"]].copy()
        r["horizon"] = h
        r["htsi_q10"] = ms["htsi_q10"].predict(X[feats]) - qhat
        r["htsi_q50"] = ms["htsi_q50"].predict(X[feats])
        r["htsi_q90"] = ms["htsi_q90"].predict(X[feats]) + qhat
        # enforce non-crossing and the 0-100 range
        r["htsi_q50"] = r["htsi_q50"].clip(0, 100)
        r["htsi_q10"] = np.minimum(r["htsi_q10"], r["htsi_q50"]).clip(0, 100)
        r["htsi_q90"] = np.maximum(r["htsi_q90"], r["htsi_q50"]).clip(0, 100)
        if "p_warning" in ms:
            # Direct exceedance classifiers: the quantile-derived probability
            # never reached a Warning day on held-out data.
            r["p_warning"] = ms["p_warning"].predict(X[feats])
            r["p_watch"] = ms["p_watch"].predict(X[feats])
        else:
            r["p_warning"] = _prob_exceed(r["htsi_q10"], r["htsi_q50"], r["htsi_q90"], warn)
            r["p_watch"] = _prob_exceed(r["htsi_q10"], r["htsi_q50"], r["htsi_q90"], settings.alerts.band_edges[0])
        for v in POINT_TARGETS:
            r[v] = ms[v].predict(X[feats])
        if explain:
            import shap
            sv = shap.TreeExplainer(ms["htsi_q50"]).shap_values(X[feats])
            top = np.argsort(-np.abs(sv), axis=1)[:, :4]
            r["drivers"] = [
                [{"feature": feats[j], "label": FEATURE_LABELS.get(feats[j], feats[j]),
                  "value": round(float(X[feats].iloc[i, j]), 2), "contribution": round(float(sv[i, j]), 2)}
                 for j in top[i]]
                for i in range(len(X))
            ]
        out.append(r)
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------------------
# Exceedance classifiers -- the models that actually catch dangerous days
# ---------------------------------------------------------------------------
#
# The quantile median is the right point forecast and the wrong alarm. Median
# regression shrinks toward typical values, so on held-out 2024-2025 data it
# never once predicted a Warning day (F1 = 0.00 at every lead), and neither did
# P(Warning+) read off the three quantiles. Warning days are the top ~3% of
# summer days; detecting them is a rare-event classification problem and is
# modelled as one: a binary LightGBM per lead time and per level, with the
# decision threshold chosen on the 2023 validation year to maximise F1 and then
# frozen before the test years are scored.

EXCEEDANCE_LEVELS = {"watch": 0, "warning": 1}


def _auc(y: np.ndarray, p: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else float("nan")


def _pr_auc(y: np.ndarray, p: np.ndarray) -> float:
    from sklearn.metrics import average_precision_score
    return float(average_precision_score(y, p)) if y.sum() > 0 else float("nan")


def _prf(pred: np.ndarray, obs: np.ndarray) -> dict:
    tp = int((pred & obs).sum()); fp = int((pred & ~obs).sum()); fn = int((~pred & obs).sum())
    p = tp / max(tp + fp, 1); r = tp / max(tp + fn, 1)
    return {"precision": round(p, 3), "recall": round(r, 3), "f1": round(2 * p * r / max(p + r, 1e-9), 3),
            "tp": tp, "fp": fp, "fn": fn}


def _best_threshold(y: np.ndarray, p: np.ndarray) -> float:
    grid = np.linspace(0.02, 0.9, 89)
    f1 = [_prf(p >= t, y)["f1"] for t in grid]
    return float(grid[int(np.argmax(f1))])


def train_exceedance() -> dict:
    """Train Watch+ / Warning+ classifiers for every lead; add them to the metadata."""
    cfg = settings.forecast
    meta = json.loads((ARTIFACT_DIR / "metadata.json").read_text())
    df = load_training_frame()
    clim = pd.read_parquet(ARTIFACT_DIR / "clim_htsi.parquet")
    edges = settings.alerts.band_edges
    meta["exceedance"] = {}

    for h in cfg.horizons:
        t0 = time.time()
        X = build_features(df, clim, h).dropna(subset=["y_htsi", "htsi_r14", "clim_p90_target"])
        feats = feature_columns(X)
        tr = X[X["target_date"] <= cfg.train_end]
        va = X[(X["target_date"] > cfg.train_end) & (X["target_date"] <= cfg.valid_end)]
        te = X[X["target_date"] > cfg.valid_end]
        out = {}
        for level, ei in EXCEEDANCE_LEVELS.items():
            edge = edges[ei]
            ytr = (tr["y_htsi"] >= edge).astype(int)
            yva = (va["y_htsi"] >= edge).astype(int)
            yte = (te["y_htsi"] >= edge).to_numpy()
            params = _lgb_params("binary")
            params.update({"num_leaves": 31, "min_data_in_leaf": 200})
            m = _fit(tr[feats], ytr, va[feats], yva, params, rounds=1500)
            thr = _best_threshold(yva.to_numpy().astype(bool), m.predict(va[feats]))
            p = m.predict(te[feats])
            persist = te["htsi_l0"].to_numpy() >= edge
            base = yte.mean()
            brier = float(np.mean((p - yte) ** 2))
            bins = np.linspace(0, 1, 11)
            idx = np.clip(np.digitize(p, bins) - 1, 0, 9)
            out[level] = {
                "edge": edge, "threshold": round(thr, 3), "base_rate_test": round(float(base), 4),
                "model": _prf(p >= thr, yte), "persistence": _prf(persist, yte),
                "auc": round(_auc(yte, p), 3), "pr_auc": round(_pr_auc(yte, p), 3),
                "pr_auc_base": round(float(base), 4),
                "brier": round(brier, 4), "brier_skill_vs_base_rate": round(1 - brier / max(base * (1 - base), 1e-12), 3),
                "reliability": [
                    {"bin": round(float((bins[i] + bins[i + 1]) / 2), 2), "n": int((idx == i).sum()),
                     "observed": round(float(yte[idx == i].mean()), 3) if (idx == i).any() else None}
                    for i in range(10)
                ],
            }
            m.save_model(str(ARTIFACT_DIR / f"h{h}_p_{level}.txt"))
        meta["exceedance"][str(h)] = out
        w = out["warning"]
        log.info("D+%d exceedance | Warning+: AUC %.3f  F1 %.2f (P %.2f R %.2f @ %.2f) vs persistence %.2f | Watch+: AUC %.3f F1 %.2f | %.0fs",
                 h, w["auc"], w["model"]["f1"], w["model"]["precision"], w["model"]["recall"], w["threshold"],
                 w["persistence"]["f1"], out["watch"]["auc"], out["watch"]["model"]["f1"], time.time() - t0)

    (ARTIFACT_DIR / "metadata.json").write_text(json.dumps(meta, indent=2))
    return meta
