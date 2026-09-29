"""Build the whole USHMA pipeline, end to end.

    python scripts/build_all.py            # run stages whose output is missing
    python scripts/build_all.py --force    # rebuild everything
    python scripts/build_all.py --from risk

Stages run in dependency order. Each one is skipped when its output already
exists, so an interrupted build resumes where it stopped.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from ushma.config import settings  # noqa: E402
from ushma.logging_setup import get_logger  # noqa: E402

log = get_logger("build")
P = settings.paths


def ingest():
    from ushma.ingest.nasapower import ingest as run
    run()


def indices():
    from ushma.indices.pipeline import build_daily
    build_daily()


def htsi():
    from ushma.climate.climatology import attach_anomaly, build_climatology
    from ushma.indices.htsi import compute_htsi
    d = pd.read_parquet(P.daily_cell_parquet)
    h = compute_htsi(attach_anomaly(d, build_climatology(d), "wbgt_max"))
    h.to_parquet(P.processed_dir / "daily_htsi.parquet", index=False, compression="zstd")


def places():
    from ushma.geo.cells import assign_cells
    from ushma.geo.wards import ward_registry
    from ushma.health.mortality import build_baseline, load_deaths
    from ushma.health.nfhs import extract_nfhs
    from ushma.health.vulnerability import build_vulnerability
    cells = pd.read_parquet(P.daily_cell_parquet, columns=["cell_id", "lat", "lon"]).drop_duplicates("cell_id")
    assign_cells(cells)
    build_baseline(load_deaths())
    extract_nfhs()
    build_vulnerability()
    ward_registry()


def risk():
    from ushma.health.district_risk import annual_summary, build_district_risk
    log.info("\n%s", annual_summary(build_district_risk()).to_string())


def forecast():
    from ushma.forecast.model import train
    train()


def export():
    from ushma.export import export_all
    export_all()


STAGES = [
    ("ingest", ingest, P.hourly_grid_dir / "year=2025" / "part.parquet"),
    ("indices", indices, P.daily_cell_parquet),
    ("htsi", htsi, P.processed_dir / "daily_htsi.parquet"),
    ("places", places, P.processed_dir / "wards.parquet"),
    ("risk", risk, P.processed_dir / "district_risk_daily.parquet"),
    ("forecast", forecast, P.artifacts_dir / "forecast" / "metadata.json"),
    ("export", export, P.data_dir / "serve" / "meta.json"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="rebuild stages even if their output exists")
    ap.add_argument("--from", dest="start", choices=[s[0] for s in STAGES], help="force-rebuild from this stage onward")
    args = ap.parse_args()

    P.ensure_dirs()
    forcing = args.force
    for name, fn, output in STAGES:
        if args.start == name:
            forcing = True
        if output.exists() and not forcing:
            log.info("[%s] up to date (%s)", name, output.relative_to(ROOT))
            continue
        t = time.time()
        log.info("[%s] running", name)
        fn()
        log.info("[%s] done in %.0fs", name, time.time() - t)
        # Everything downstream of a rebuilt stage is stale.
        forcing = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
