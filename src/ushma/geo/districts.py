"""Canonical district table and crosswalk for Odisha's 30 districts.

Four sources in this project name districts four different ways:

=========================  ==============================  ==================
Source                     Key                             Example (Khordha)
=========================  ==============================  ==================
AHS mortality file         integer 1-30                    ``17``
HVI file                   upper-case name + ``dist_code``  ``KHORDHA`` / 386
NFHS-5 fact sheets         title-case name                  ``Khordha``
Supplied weather notebook  ``District_City`` string         ``Khordha_Bhubaneswar``
=========================  ==============================  ==================

and the spellings diverge (``KEONJHAR (KENDUJHAR)`` / ``Kendujhar``,
``NUAPARHA`` / ``NUAPADA``, ``SUBARNAPUR`` / ``SONAPUR``, ``BALASORE`` /
``BALESHWAR`` ...). This module is the single place those are reconciled. Every
join in the pipeline goes through :func:`resolve`, and
``tests/test_crosswalk.py`` asserts that every key in every source resolves.

The canonical key is the AHS district code, because it is the key on the only
individual-level health data we have. The Census 2011 district code is carried
alongside: Census 2011 numbers Odisha's districts 361-390 in the same order the
AHS uses 1-30.

Headquarters coordinates are approximate town centres, used for mapping
district labels and for assigning grid cells to districts in the absence of
boundary polygons (see :mod:`ushma.geo.cells`). Populations are Census 2011.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

__all__ = ["DISTRICTS", "district_table", "resolve", "normalise"]


@dataclass(frozen=True)
class District:
    ahs_code: int
    name: str            # canonical (AHS codebook spelling)
    hvi_name: str        # as written in india_district_hvi_final.csv
    nfhs_name: str       # as written in the NFHS-5 fact sheets
    hq: str
    lat: float
    lon: float
    pop_2011: int
    aliases: tuple[str, ...] = ()
    # Approximate geographic centroid and area. Headquarters are frequently at a
    # district's edge (Nuapada, Malkangiri, Baripada), so cell assignment uses
    # these rather than the HQ.
    c_lat: float = 0.0
    c_lon: float = 0.0
    area_km2: int = 0

    @property
    def census_2011_code(self) -> int:
        return 360 + self.ahs_code


DISTRICTS: tuple[District, ...] = (
    District(1, "BARGARH", "BARGARH", "Bargarh", "Bargarh", 21.333, 83.619, 1_481_255, c_lat=21.25, c_lon=83.45, area_km2=5837),
    District(2, "JHARSUGUDA", "JHARSUGUDA", "Jharsuguda", "Jharsuguda", 21.855, 84.006, 579_505, c_lat=21.8, c_lon=84.05, area_km2=2081),
    District(3, "SAMBALPUR", "SAMBALPUR", "Sambalpur", "Sambalpur", 21.467, 83.981, 1_041_099, c_lat=21.45, c_lon=84.25, area_km2=6657),
    District(4, "DEBAGARH", "DEOGARH", "Debagarh", "Debagarh", 21.538, 84.733, 312_520, ("DEOGARH",), c_lat=21.55, c_lon=84.75, area_km2=2940),
    District(5, "SUNDARGARH", "SUNDARGARH", "Sundargarh", "Sundargarh", 22.117, 84.030, 2_093_437, c_lat=22.1, c_lon=84.45, area_km2=9712),
    District(6, "KENDUJHAR", "KEONJHAR (KENDUJHAR)", "Kendujhar", "Kendujhar", 21.630, 85.582, 1_801_733, ("KEONJHAR",), c_lat=21.55, c_lon=85.55, area_km2=8303),
    District(7, "MAYURBHANJ", "MAYURBHANJ", "Mayurbhanj", "Baripada", 21.936, 86.727, 2_519_738, c_lat=21.9, c_lon=86.3, area_km2=10418),
    District(8, "BALESHWAR", "BALASORE", "Baleshwar", "Balasore", 21.494, 86.932, 2_320_529, ("BALASORE",), c_lat=21.45, c_lon=86.75, area_km2=3806),
    District(9, "BHADRAK", "BHADRAK", "Bhadrak", "Bhadrak", 21.058, 86.496, 1_506_337, c_lat=21.05, c_lon=86.55, area_km2=2505),
    District(10, "KENDRAPARA", "KENDRAPARA", "Kendrapara", "Kendrapara", 20.502, 86.422, 1_440_361, c_lat=20.55, c_lon=86.6, area_km2=2644),
    District(11, "JAGATSINGHAPUR", "JAGATSINGHPUR", "Jagatsinghapur", "Jagatsinghapur", 20.256, 86.171, 1_136_971, ("JAGATSINGHPUR",), c_lat=20.2, c_lon=86.3, area_km2=1668),
    District(12, "CUTTACK", "CUTTACK", "Cuttack", "Cuttack", 20.463, 85.883, 2_624_470, c_lat=20.45, c_lon=85.8, area_km2=3932),
    District(13, "JAJAPUR", "JAJAPUR", "Jajapur", "Jajpur", 20.849, 86.334, 1_827_192, ("JAJPUR",), c_lat=20.85, c_lon=86.1, area_km2=2899),
    District(14, "DHENKANAL", "DHENKANAL", "Dhenkanal", "Dhenkanal", 20.659, 85.598, 1_192_811, c_lat=20.75, c_lon=85.55, area_km2=4452),
    District(15, "ANUGUL", "ANUGUL", "Anugul", "Angul", 20.840, 85.102, 1_273_821, ("ANGUL",), c_lat=21.0, c_lon=84.95, area_km2=6375),
    District(16, "NAYAGARH", "NAYAGARH", "Nayagarh", "Nayagarh", 20.129, 85.096, 962_789, c_lat=20.15, c_lon=85.0, area_km2=3890),
    District(17, "KHORDHA", "KHORDHA", "Khordha", "Bhubaneswar", 20.296, 85.825, 2_251_673, ("KHURDA", "KHORDHA_BHUBANESWAR"), c_lat=20.1, c_lon=85.55, area_km2=2813),
    District(18, "PURI", "PURI", "Puri", "Puri", 19.813, 85.831, 1_698_730, c_lat=19.85, c_lon=85.8, area_km2=3479),
    District(19, "GANJAM", "GANJAM", "Ganjam", "Chhatrapur", 19.315, 84.794, 3_529_031, c_lat=19.55, c_lon=84.7, area_km2=8206),
    District(20, "GAJAPATI", "GAJAPATI", "Gajapati", "Paralakhemundi", 18.781, 84.093, 577_817, c_lat=19.05, c_lon=84.1, area_km2=4325),
    District(21, "KANDHAMAL", "KANDHAMAL", "Kandhamal", "Phulbani", 20.471, 84.233, 733_110, c_lat=20.25, c_lon=84.1, area_km2=8021),
    District(22, "BAUDH", "BOUDH", "Baudh", "Baudh", 20.836, 84.325, 441_162, ("BOUDH",), c_lat=20.65, c_lon=84.3, area_km2=3098),
    District(23, "SONAPUR", "SUBARNAPUR", "Subarnapur", "Sonepur", 20.833, 83.913, 610_183, ("SUBARNAPUR", "SONEPUR"), c_lat=20.85, c_lon=83.85, area_km2=2337),
    District(24, "BALANGIR", "BALANGIR", "Balangir", "Balangir", 20.707, 83.484, 1_648_997, ("BOLANGIR",), c_lat=20.6, c_lon=83.3, area_km2=6575),
    District(25, "NUAPADA", "NUAPARHA", "Nuapada", "Nuapada", 20.817, 82.534, 610_382, ("NUAPARHA",), c_lat=20.6, c_lon=82.6, area_km2=3852),
    District(26, "KALAHANDI", "KALAHANDI", "Kalahandi", "Bhawanipatna", 19.907, 83.167, 1_576_869, c_lat=19.95, c_lon=83.15, area_km2=7920),
    District(27, "RAYAGADA", "RAYAGARHA", "Rayagada", "Rayagada", 19.171, 83.416, 967_911, ("RAYAGARHA",), c_lat=19.35, c_lon=83.5, area_km2=7073),
    District(28, "NABARANGAPUR", "NABARANGAPUR", "Nabarangapur", "Nabarangpur", 19.232, 82.549, 1_220_946, ("NABARANGPUR",), c_lat=19.4, c_lon=82.35, area_km2=5291),
    District(29, "KORAPUT", "KORAPUT", "Koraput", "Koraput", 18.812, 82.711, 1_379_647, c_lat=18.75, c_lon=82.75, area_km2=8807),
    District(30, "MALKANGIRI", "MALKANGIRI", "Malkangiri", "Malkangiri", 18.348, 81.888, 613_192, c_lat=18.3, c_lon=81.95, area_km2=5791),
)


def normalise(name: str) -> str:
    """Upper-case, strip punctuation and parenthetical alternates."""
    s = str(name).upper().strip()
    s = s.replace("-", " ").replace(".", " ")
    s = re.sub(r"\s+", " ", s)
    return s


def _lookup() -> dict[str, int]:
    table: dict[str, int] = {}
    for d in DISTRICTS:
        keys = {d.name, d.hvi_name, d.nfhs_name, d.hq, *d.aliases}
        # the parenthetical inside "KEONJHAR (KENDUJHAR)"
        for m in re.findall(r"\(([^)]+)\)", d.hvi_name):
            keys.add(m)
        for k in keys:
            table[normalise(k)] = d.ahs_code
    return table


_LOOKUP = _lookup()


def resolve(key: str | int) -> int:
    """Map any known district identifier to its canonical AHS code.

    Raises ``KeyError`` rather than guessing -- a silent mis-join is the most
    common way a pipeline like this produces confident nonsense.
    """
    if isinstance(key, (int,)) or (isinstance(key, str) and key.strip().isdigit()):
        code = int(key)
        if 1 <= code <= 30:
            return code
        if 361 <= code <= 390:
            return code - 360
        raise KeyError(f"district code {key} is neither AHS (1-30) nor Census 2011 (361-390)")
    k = normalise(key)
    if k in _LOOKUP:
        return _LOOKUP[k]
    # "Khordha_Bhubaneswar" style: try the first token
    first = normalise(re.split(r"[_/]", str(key))[0])
    if first in _LOOKUP:
        return _LOOKUP[first]
    raise KeyError(f"unresolvable district identifier: {key!r}")


def district_table() -> pd.DataFrame:
    """The canonical table as a DataFrame."""
    return pd.DataFrame(
        [
            {
                "ahs_code": d.ahs_code,
                "census_2011_code": d.census_2011_code,
                "district": d.name,
                "hvi_name": d.hvi_name,
                "nfhs_name": d.nfhs_name,
                "hq": d.hq,
                "hq_lat": d.lat,
                "hq_lon": d.lon,
                "pop_2011": d.pop_2011,
                "c_lat": d.c_lat,
                "c_lon": d.c_lon,
                "area_km2": d.area_km2,
            }
            for d in DISTRICTS
        ]
    )
