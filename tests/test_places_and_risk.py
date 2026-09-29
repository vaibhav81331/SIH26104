"""Crosswalk, health data and risk model.

These guard the failure modes that produce confident nonsense without any error:
a district that silently fails to join, a death counted twice, a risk curve
that attributes deaths to a pleasant winter day.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ushma.config import settings
from ushma.geo.districts import DISTRICTS, district_table, resolve
from ushma.health.risk import load_exposure_response, log_rr_eff, mri_from_rr, relative_risk

PROC = settings.paths.processed_dir


def _need(name: str) -> pd.DataFrame:
    p = PROC / name
    if not p.exists():
        pytest.skip(f"{name} not built")
    return pd.read_parquet(p)


# ---------------------------------------------------------------------------
# Crosswalk
# ---------------------------------------------------------------------------


def test_thirty_districts_matching_census_totals():
    t = district_table()
    assert len(t) == 30
    assert t["ahs_code"].tolist() == list(range(1, 31))
    assert t["pop_2011"].sum() == 41_974_218  # Census 2011, Odisha
    assert sum(d.area_km2 for d in DISTRICTS) == 155_707


@pytest.mark.parametrize(
    "name, code",
    [
        ("KEONJHAR (KENDUJHAR)", 6), ("Kendujhar", 6), ("BALASORE", 8), ("Baleshwar", 8),
        ("NUAPARHA", 25), ("SUBARNAPUR", 23), ("Sonepur", 23), ("Bolangir", 24),
        ("Khordha_Bhubaneswar", 17), ("JAGATSINGHPUR", 11), ("DEOGARH", 4), ("BOUDH", 22),
        (17, 17), ("377", 17),
    ],
)
def test_every_spelling_resolves(name, code):
    assert resolve(name) == code


def test_unknown_district_fails_loudly():
    with pytest.raises(KeyError):
        resolve("ATLANTIS")


def test_every_source_key_resolves():
    """No row may be dropped on any join because a district name failed to match."""
    hvi = pd.read_csv(settings.paths.hvi_india_csv, dtype={"dist_code": str})
    names = hvi.loc[hvi["state"].str.upper() == "ODISHA", "district"]
    assert sorted(names.map(resolve)) == list(range(1, 31))

    from ushma.health.mortality import read_codebook_districts
    cb = read_codebook_districts()
    assert sorted(cb["codebook_name"].map(resolve)) == list(range(1, 31))


def test_cell_assignment_covers_every_district():
    c = _need("cell_district.parquet")
    inside = c[c["in_odisha"]]
    assert inside["ahs_code"].nunique() == 30
    # Odisha is ~155,700 km^2; at ~725 km^2 a cell the stand-in should be close.
    assert 190 <= len(inside) <= 250
    assert not c.loc[c["is_sea"], "in_odisha"].any()


# ---------------------------------------------------------------------------
# Health data
# ---------------------------------------------------------------------------


def test_mortality_deduplication_removes_the_round_duplicates():
    from ushma.health.mortality import load_deaths
    d = load_deaths()
    assert len(d) == 94_619 - 23_269
    # Only the decedent's own sex column is read -- never the household head's.
    assert "sex" not in d.columns and "deceased_sex" in d.columns


def test_baseline_is_plausible():
    b = _need("baseline_mortality.parquet")
    per_year = b.groupby("ahs_code")["expected_deaths"].sum().sum()
    pop = b.groupby("ahs_code")["pop_now"].first().sum()
    cdr = 1000 * per_year / pop
    assert cdr == pytest.approx(settings.risk.current_cdr_per_1000, rel=0.05)
    # Seasonal factor averages to one over the year.
    assert b.groupby("ahs_code")["seasonal_factor"].mean().between(0.99, 1.01).all()


def test_nfhs_extraction_is_complete_and_in_range():
    n = _need("nfhs5_districts.parquet")
    assert len(n) == 30
    vals = n.drop(columns=["nfhs_name", "ahs_code"])
    assert not vals.isna().any().any()
    assert ((vals >= 0) & (vals <= 100)).all().all()
    anugul = n[n["nfhs_name"] == "Anugul"].iloc[0]
    # Spot-checked against the printed fact sheet.
    assert anugul["women_high_bp_pct"] == 18.9
    assert anugul["men_high_bp_pct"] == 21.1
    assert anugul["men_high_sugar_pct"] == 18.2


def test_vulnerability_excludes_flat_columns_and_varies():
    v = _need("vulnerability.parquet")
    assert v["vuln_score"].between(0, 1).all()
    assert v["vuln_score"].nunique() > 25
    lo, hi = settings.risk.vuln_mult_min, settings.risk.vuln_mult_max
    assert v["vuln_mult"].between(lo - 1e-9, hi + 1e-9).all()
    for flat in ("mpi_poverty_pct", "literacy_pct", "outdoor_workers_pct", "sc_st_pct"):
        assert flat not in v.columns


# ---------------------------------------------------------------------------
# Risk model
# ---------------------------------------------------------------------------


def test_exposure_response_hits_its_reference_point():
    er = load_exposure_response()
    rr = relative_risk(np.full((1, 4), er.reference_htsi), 1.0, er)[0]
    assert rr == pytest.approx(er.rr_ref, rel=1e-6)
    assert np.isclose(sum(er.lag_weights), 1.0)


def test_no_excess_risk_below_threshold():
    er = load_exposure_response()
    assert relative_risk(np.full((1, 4), er.threshold - 1), 1.3, er)[0] == 1.0


def test_vulnerability_modifies_risk_on_the_log_scale():
    er = load_exposure_response()
    h = np.full((1, 4), er.reference_htsi)
    base = log_rr_eff(h, er)[0]
    assert np.log(relative_risk(h, 1.3, er)[0]) == pytest.approx(1.3 * base)


def test_risk_is_capped_and_mri_bounded():
    er = load_exposure_response()
    assert relative_risk(np.full((1, 4), 100.0), 1.0, er)[0] <= er.max_rr + 1e-9
    assert mri_from_rr(np.array([0.9, 1.0, 1.25, 5.0]), er).tolist() == [0.0, 0.0, 50.0, 100.0]


def test_interval_brackets_the_central_estimate():
    er = load_exposure_response()
    h = np.full((1, 4), 66.0)
    lo, mid, hi = (relative_risk(h, 1.0, er, w)[0] for w in ("low", "central", "high"))
    assert lo < mid < hi


def test_attributed_deaths_follow_the_heat_season():
    """The regression that caught the winter and October artefacts."""
    r = _need("district_risk_daily.parquet")
    m = r.assign(m=pd.DatetimeIndex(r["date"]).month).groupby("m")["excess_deaths"].sum()
    assert m.idxmax() in (4, 5, 6), f"peak month {m.idxmax()}"
    assert m[[12, 1]].sum() < 0.02 * m.sum(), "heat deaths attributed to mid-winter"
    assert m[[4, 5, 6]].sum() > m[[10, 11, 12]].sum() * 3


def test_ward_ids_are_unique():
    """Balasore and Balangir once both produced "BAL-" ids; 21 wards vanished."""
    w = _need("wards.parquet")
    assert not w["ward_id"].duplicated().any()
    from ushma.geo.wards import CITIES
    assert len(w) == sum(c.wards for c in CITIES) if w["synthetic"].all() else True
