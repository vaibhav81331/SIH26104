"""Ward registry: real boundaries when supplied, a labelled synthetic stand-in otherwise.

The contract
------------
Drop a GeoJSON FeatureCollection at ``data/geo/wards.geojson`` (EPSG:4326).
Each feature needs these properties:

==============  ======================================================
``ward_id``     unique, stable identifier
``ward_name``   display name
``ulb_name``    urban local body, e.g. ``Bhubaneswar Municipal Corporation``
``district``    any spelling the crosswalk understands
==============  ======================================================

and may carry ``population``, ``elderly_pct``, ``slum_pop_pct``,
``built_up_frac``, ``ndvi``. Missing optional fields are filled from district
values and the fill is recorded per ward. A shapefile converts with
``ogr2ogr -f GeoJSON -t_srs EPSG:4326 wards.geojson wards.shp``.

:func:`load_wards` validates that contract and **fails with a precise message**
rather than guessing -- a ward silently dropped from an alert system is a
neighbourhood that never gets warned.

The stand-in
------------
Until real boundaries arrive, :func:`synthetic_wards` builds a ward layer for
Odisha's eight largest cities with the real ward counts (Bhubaneswar 67,
Cuttack 59, Berhampur 42, Sambalpur 41, Rourkela 40, Puri 32, Balasore 30,
Balangir 21), laid out as a Voronoi partition of an evenly spaced spiral inside
each city's approximate footprint. Attributes follow a plausible core-to-edge
gradient and are seeded, so every run is identical. **Every synthetic ward
carries ``synthetic=True``, and the dashboard labels it.** None of the synthetic
geometry or attributes should be read as describing a real ward.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import MultiPolygon, Point, Polygon, mapping, shape

from ushma.config import settings
from ushma.geo.districts import district_table, resolve
from ushma.logging_setup import get_logger

log = get_logger(__name__)

__all__ = ["load_wards", "synthetic_wards", "ward_registry", "CITIES", "REQUIRED_FIELDS"]

REQUIRED_FIELDS = ("ward_id", "ward_name", "ulb_name", "district")
OPTIONAL_FIELDS = ("population", "elderly_pct", "slum_pop_pct", "built_up_frac", "ndvi")


@dataclass(frozen=True)
class City:
    ulb: str
    short: str
    code: str  # ward-id prefix; must be unique (Balasore and Balangir share "BAL")
    district: str
    lat: float
    lon: float
    wards: int
    population_2011: int
    area_km2: float


#: Ward counts are the real municipal ward counts; populations are Census 2011
#: urban-local-body figures (approximate); areas are approximate footprints.
CITIES: tuple[City, ...] = (
    City("Bhubaneswar Municipal Corporation", "Bhubaneswar", "BBS", "KHORDHA", 20.2961, 85.8245, 67, 837_737, 186.0),
    City("Cuttack Municipal Corporation", "Cuttack", "CTC", "CUTTACK", 20.4625, 85.8830, 59, 606_007, 192.0),
    City("Berhampur Municipal Corporation", "Berhampur", "BAM", "GANJAM", 19.3149, 84.7941, 42, 356_598, 87.0),
    City("Sambalpur Municipal Corporation", "Sambalpur", "SBP", "SAMBALPUR", 21.4669, 83.9812, 41, 183_383, 60.0),
    City("Rourkela Municipal Corporation", "Rourkela", "RKL", "SUNDARGARH", 22.2604, 84.8536, 40, 302_955, 120.0),
    City("Puri Municipality", "Puri", "PUR", "PURI", 19.8135, 85.8312, 32, 200_564, 17.0),
    City("Balasore Municipality", "Balasore", "BLS", "BALESHWAR", 21.4942, 86.9317, 30, 118_202, 30.0),
    City("Balangir Municipality", "Balangir", "BLG", "BALANGIR", 20.7074, 83.4843, 21, 98_238, 25.0),
)


# ---------------------------------------------------------------------------
# Real boundaries
# ---------------------------------------------------------------------------


class WardContractError(ValueError):
    """The supplied ward file does not meet the documented contract."""


def load_wards(path: Path) -> pd.DataFrame:
    """Load and validate a ward GeoJSON against the contract."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    feats = raw.get("features")
    if raw.get("type") != "FeatureCollection" or not isinstance(feats, list) or not feats:
        raise WardContractError(f"{path}: expected a non-empty GeoJSON FeatureCollection")

    problems: list[str] = []
    rows = []
    seen: set[str] = set()
    vuln = pd.read_parquet(settings.paths.processed_dir / "vulnerability.parquet").set_index("ahs_code")

    for i, f in enumerate(feats):
        props = f.get("properties") or {}
        missing = [k for k in REQUIRED_FIELDS if props.get(k) in (None, "")]
        if missing:
            problems.append(f"feature {i}: missing required {missing}")
            continue
        wid = str(props["ward_id"])
        if wid in seen:
            problems.append(f"feature {i}: duplicate ward_id {wid!r}")
        seen.add(wid)
        try:
            code = resolve(props["district"])
        except KeyError as e:
            problems.append(f"feature {i} ({wid}): {e}")
            continue
        try:
            geom = shape(f["geometry"])
        except Exception as e:  # noqa: BLE001 -- report and continue collecting
            problems.append(f"feature {i} ({wid}): invalid geometry ({e})")
            continue
        if not isinstance(geom, (Polygon, MultiPolygon)):
            problems.append(f"feature {i} ({wid}): geometry must be Polygon or MultiPolygon")
            continue
        c = geom.representative_point()
        filled = []
        rec = {
            "ward_id": wid,
            "ward_name": str(props["ward_name"]),
            "ulb_name": str(props["ulb_name"]),
            "ahs_code": code,
            "lat": c.y,
            "lon": c.x,
            "area_km2": geom.area * (111.0 * 111.0 * np.cos(np.radians(c.y))),
            "geometry": mapping(geom),
            "synthetic": False,
        }
        for k in OPTIONAL_FIELDS:
            v = props.get(k)
            if v in (None, ""):
                filled.append(k)
                v = {
                    "elderly_pct": vuln.loc[code, "elderly_pct"],
                    "built_up_frac": 0.5,
                    "ndvi": 0.3,
                    "slum_pop_pct": 15.0,
                    "population": np.nan,
                }[k]
            rec[k] = float(v)
        rec["filled_fields"] = ",".join(filled)
        rows.append(rec)

    if problems:
        raise WardContractError(
            f"{path}: {len(problems)} problem(s) in the ward file; nothing was loaded.\n  "
            + "\n  ".join(problems[:20])
        )
    df = pd.DataFrame(rows)
    log.info("wards: loaded %d real wards from %s", len(df), path)
    return df


# ---------------------------------------------------------------------------
# Synthetic stand-in
# ---------------------------------------------------------------------------


def _spiral(n: int, radius_km: float) -> np.ndarray:
    """Evenly spaced points in a disc (Vogel's sunflower spiral)."""
    golden = np.pi * (3 - np.sqrt(5))
    k = np.arange(n) + 0.5
    r = radius_km * np.sqrt(k / n)
    th = k * golden
    return np.column_stack([r * np.cos(th), r * np.sin(th)])


def _voronoi_cells(pts: np.ndarray, radius_km: float) -> list[Polygon]:
    """Voronoi cells of ``pts`` clipped to a disc, in local km coordinates."""
    from scipy.spatial import Voronoi

    far = radius_km * 10
    mirror = np.vstack([pts, [[far, far], [-far, far], [far, -far], [-far, -far]]])
    vor = Voronoi(mirror)
    disc = Point(0, 0).buffer(radius_km * 1.05, resolution=48)
    cells = []
    for i in range(len(pts)):
        region = vor.regions[vor.point_region[i]]
        if -1 in region or not region:
            poly = Point(pts[i]).buffer(radius_km / np.sqrt(len(pts)))
        else:
            poly = Polygon(vor.vertices[region])
        cells.append(poly.intersection(disc))
    return cells


def synthetic_wards(seed: int = 20260923) -> pd.DataFrame:
    """Build the labelled synthetic ward layer for :data:`CITIES`."""
    rng = np.random.default_rng(seed)
    vuln = pd.read_parquet(settings.paths.processed_dir / "vulnerability.parquet").set_index("ahs_code")
    rows = []
    for city in CITIES:
        code = resolve(city.district)
        radius = np.sqrt(city.area_km2 / np.pi)
        pts = _spiral(city.wards, radius)
        pts += rng.normal(0, radius / np.sqrt(city.wards) * 0.18, pts.shape)
        cells = _voronoi_cells(pts, radius)

        dist = np.hypot(pts[:, 0], pts[:, 1]) / radius  # 0 core -> 1 edge
        built = np.clip(0.88 - 0.55 * dist + rng.normal(0, 0.06, len(pts)), 0.1, 0.95)
        ndvi = np.clip(0.12 + 0.42 * dist + rng.normal(0, 0.05, len(pts)), 0.05, 0.7)
        density = np.exp(-1.6 * dist) * rng.lognormal(0, 0.25, len(pts))
        areas = np.array([c.area for c in cells])
        pop_w = density * areas
        pop = city.population_2011 * settings.risk.population_growth_since_2011 * pop_w / pop_w.sum()
        # Slums cluster: a few pockets rather than uniform noise.
        pockets = rng.uniform(-radius * 0.7, radius * 0.7, (3, 2))
        pk = np.min(np.hypot(pts[:, None, 0] - pockets[None, :, 0], pts[:, None, 1] - pockets[None, :, 1]), axis=1)
        slum = np.clip(38 * np.exp(-(pk / (radius * 0.25)) ** 2) + rng.uniform(3, 9, len(pts)), 2, 55)
        elderly = np.clip(vuln.loc[code, "elderly_pct"] + rng.normal(0, 1.4, len(pts)) + 1.2 * (1 - dist), 5, 20)

        kx = 111.0 * np.cos(np.radians(city.lat))
        for i, poly in enumerate(cells):
            coords = np.asarray(poly.exterior.coords)
            lonlat = np.column_stack([city.lon + coords[:, 0] / kx, city.lat + coords[:, 1] / 111.0])
            geom = Polygon(lonlat)
            rows.append(
                {
                    "ward_id": f"{city.code}-{i + 1:02d}",
                    "ward_name": f"{city.short} Ward {i + 1}",
                    "ulb_name": city.ulb,
                    "city": city.short,
                    "ahs_code": code,
                    "lat": city.lat + pts[i, 1] / 111.0,
                    "lon": city.lon + pts[i, 0] / kx,
                    "area_km2": float(poly.area),
                    "population": float(round(pop[i])),
                    "elderly_pct": float(round(elderly[i], 2)),
                    "slum_pop_pct": float(round(slum[i], 1)),
                    "built_up_frac": float(round(built[i], 3)),
                    "ndvi": float(round(ndvi[i], 3)),
                    "core_distance": float(round(dist[i], 3)),
                    "geometry": mapping(geom),
                    "synthetic": True,
                    "filled_fields": "",
                }
            )
    df = pd.DataFrame(rows)
    if df["ward_id"].duplicated().any():
        raise ValueError(f"duplicate synthetic ward ids: {df.loc[df['ward_id'].duplicated(), 'ward_id'].tolist()[:5]}")
    log.info("wards: generated %d SYNTHETIC wards across %d cities", len(df), len(CITIES))
    return df


def ward_registry() -> pd.DataFrame:
    """Real wards if supplied, otherwise the synthetic stand-in. Adds a ward vulnerability."""
    real = settings.paths.geo_dir / "wards.geojson"
    df = load_wards(real) if real.exists() else synthetic_wards()
    if "city" not in df:
        df["city"] = df["ulb_name"]

    vuln = pd.read_parquet(settings.paths.processed_dir / "vulnerability.parquet").set_index("ahs_code")
    dt = district_table().set_index("ahs_code")
    df["district"] = df["ahs_code"].map(dt["district"])
    base = df["ahs_code"].map(vuln["vuln_score"]).to_numpy()

    # Ward vulnerability: the district score adjusted by what varies inside a
    # city -- elderly share, slum share (poor housing, no cooling) and built-up
    # fraction (heat retention) relative to the city mean.
    def z(col: str) -> np.ndarray:
        g = df.groupby("city")[col]
        return ((df[col] - g.transform("mean")) / g.transform("std").replace(0, 1)).fillna(0).to_numpy()

    adj = 0.06 * z("elderly_pct") + 0.08 * z("slum_pop_pct") + 0.05 * z("built_up_frac")
    score = np.clip(base + adj, 0.0, 1.0)
    df["vuln_score"] = score
    lo, hi = settings.risk.vuln_mult_min, settings.risk.vuln_mult_max
    df["vuln_mult"] = lo + (hi - lo) * score

    out = settings.paths.processed_dir / "wards.parquet"
    df.assign(geometry=df["geometry"].map(json.dumps)).to_parquet(out, index=False)
    return df
