"""Extract district indicators from the NFHS-5 (2019-21) fact sheets in ``Odisha.pdf``.

Why this exists
---------------
The supplied HVI file carries four socio-economic columns -- poverty, literacy,
outdoor workers, SC/ST share -- that are a national fallback block, identical
for all 30 Odisha districts. A vulnerability index built on them would rate
every district the same on half its inputs. The NFHS-5 district fact sheets in
the same folder carry real, varying district values, so they replace them.

Layout
------
Each district has three "Key Indicators" pages headed ``<District>, Odisha -
Key Indicators`` with two value columns, NFHS-5 (2019-21) then NFHS-4
(2015-16). The NFHS-5 value is the first number after the ``(%)`` marker; long
labels wrap, in which case the numbers sit at the start of the next line.
Values in parentheses (25-49 unweighted cases) are kept; ``*`` and ``na`` become
missing.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ushma.config import settings
from ushma.geo.districts import resolve
from ushma.logging_setup import get_logger

log = get_logger(__name__)

__all__ = ["extract_nfhs", "INDICATORS"]

#: (column, regex anchored after the indicator number, occurrence).
#: Occurrence picks women (0) vs men (1) where NFHS repeats a label.
INDICATORS: tuple[tuple[str, str, int], ...] = (
    ("pop_under15_pct", r"Population below age 15 years", 0),
    ("electricity_pct", r"Population living in households with electricity", 0),
    ("improved_water_pct", r"Population living in households with an improved drinking-water", 0),
    ("improved_sanitation_pct", r"Population living in households that use an improved sanitation", 0),
    ("clean_fuel_pct", r"Households using clean fuel for cooking", 0),
    ("health_insurance_pct", r"Households with any usual member covered under a health insurance", 0),
    ("women_literate_pct", r"Women who are literate", 0),
    ("women_anaemic_pct", r"All women age 15-49 years who are anaemic", 0),
    ("women_high_bp_pct", r"Elevated blood pressure", 0),
    ("men_high_bp_pct", r"Elevated blood pressure", 1),
    ("women_high_sugar_pct", r"Blood sugar level - high or very high", 0),
    ("men_high_sugar_pct", r"Blood sugar level - high or very high", 1),
)

_LINE_START = re.compile(r"^\s*\d+\.\s*")

_NUM = re.compile(r"^\(?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\)?$")
_HEADER = re.compile(r"^(?P<name>[A-Za-z ]+), Odisha - Key Indicators")


def _first_value(tokens: list[str]) -> float | None:
    for t in tokens:
        t = t.strip()
        if t in ("*", "na"):
            return None
        m = _NUM.match(t)
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def _parse_line(lines: list[str], i: int) -> float | None:
    # The label may wrap once or twice before its "(%)" marker.
    for j in range(i, min(i + 3, len(lines))):
        line = lines[j]
        idx = line.rfind("(%)")
        if idx >= 0:
            return _first_value(line[idx + 3:].split())
    # No marker (e.g. a count indicator): numbers open the next line.
    if i + 1 < len(lines):
        return _first_value(lines[i + 1].split()[:2])
    return None


def extract_nfhs() -> pd.DataFrame:
    """One row per district with the indicators in :data:`INDICATORS`."""
    import pdfplumber

    pages: dict[str, list[str]] = {}
    with pdfplumber.open(settings.paths.nfhs_pdf) as pdf:
        for p in pdf.pages:
            text = p.extract_text() or ""
            first = text.splitlines()[0] if text else ""
            m = _HEADER.match(first.strip())
            if not m:
                continue
            pages.setdefault(m.group("name").strip(), []).extend(text.splitlines())

    rows = []
    for name, lines in pages.items():
        rec: dict[str, object] = {"nfhs_name": name, "ahs_code": resolve(name)}
        for col, pattern, occ in INDICATORS:
            rx = re.compile(pattern, re.IGNORECASE)
            hits = [
                i for i, ln in enumerate(lines)
                if _LINE_START.match(ln) and rx.match(_LINE_START.sub("", ln, count=1))
            ]
            rec[col] = _parse_line(lines, hits[occ]) if len(hits) > occ else np.nan
        rows.append(rec)

    df = pd.DataFrame(rows).sort_values("ahs_code").reset_index(drop=True)
    if len(df) != 30:
        log.warning("NFHS: expected 30 district sheets, found %d", len(df))
    missing = int(df.drop(columns=["nfhs_name", "ahs_code"]).isna().sum().sum())
    log.info("NFHS-5: %d districts x %d indicators | %d missing values",
             len(df), len(INDICATORS), missing)
    df.to_parquet(settings.paths.processed_dir / "nfhs5_districts.parquet", index=False)
    return df
