"""Regenerate reports/figures/impact_vs_temperature.png from the built data.

    python scripts/make_figure.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ushma.config import settings  # noqa: E402

# Palette roles: categorical slots 1-3 (validated all-pairs, light mode).
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
INK2, AXIS, GRID = "#52514e", "#c3c2b7", "#e1e0d9"


def main() -> None:
    P = settings.paths.processed_dir
    h = pd.read_parquet(P / "daily_htsi.parquet", columns=["cell_id", "date", "htsi_band", "t2m_max", "wbgt_max"])
    cells = pd.read_parquet(P / "cell_district.parquet")
    h = h.merge(cells[cells["in_odisha"]][["cell_id"]], on="cell_id")
    h = h[(h["date"] >= "2015-01-01") & (h["date"] <= "2025-12-31")]
    h["imd"] = h["t2m_max"] >= 40
    h["ushma"] = h["htsi_band"].isin(["Warning", "Emergency"])
    h["m"] = h["date"].dt.month

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2, "figure.dpi": 150,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(1, 3, figsize=(13, 4.0))

    g = h.groupby("m")[["ushma", "imd"]].mean() * 100
    x = np.arange(1, 13); w = 0.38
    ax[0].bar(x - w / 2, g["ushma"], w, label="USHMA  HTSI Warning+", color=S1)
    ax[0].bar(x + w / 2, g["imd"], w, label="Temperature rule  Tmax ≥ 40 °C", color=S2)
    ax[0].set_xticks(x); ax[0].set_xticklabels(list("JFMAMJJASOND"))
    ax[0].set_ylabel("% of cell-days alerted"); ax[0].grid(axis="y", color=GRID); ax[0].set_axisbelow(True)
    ax[0].set_title("(a) When each system warns", loc="left", fontweight="bold")
    ax[0].legend(frameon=False, fontsize=8)
    ax[0].annotate("monsoon: temperature\nrule is silent", xy=(7.5, 0.7), xytext=(8.0, 20), fontsize=8,
                   arrowprops=dict(arrowstyle="->", lw=0.8, color=INK2), color=INK2)

    both = h[h.imd & h.ushma]; only_u = h[h.ushma & ~h.imd]; only_i = h[h.imd & ~h.ushma]
    ax[1].scatter(only_i.t2m_max[::25], only_i.wbgt_max[::25], s=2, alpha=0.18, color=S2, label="Temperature alert only (dry heat)")
    ax[1].scatter(only_u.t2m_max[::3], only_u.wbgt_max[::3], s=2, alpha=0.3, color=S1, label="USHMA alert only (humid heat)")
    ax[1].scatter(both.t2m_max[::3], both.wbgt_max[::3], s=2, alpha=0.3, color=S3, label="Both")
    ax[1].axhline(35, ls="--", lw=0.9, color="#0b0b0b"); ax[1].text(24.3, 35.25, "WBGT 35 °C survivability limit", fontsize=7)
    ax[1].axvline(40, ls=":", lw=0.9, color=S2)
    ax[1].set_xlabel("Daily max temperature (°C)"); ax[1].set_ylabel("Daily max WBGT (°C)")
    ax[1].set_title("(b) Temperature is not the danger", loc="left", fontweight="bold")
    ax[1].legend(frameon=False, fontsize=7, markerscale=5, loc="lower right"); ax[1].set_xlim(24, 48); ax[1].set_ylim(25, 41)

    s = h[h.m.isin([3, 4, 5, 6])]
    vals = [49.7, 100 * (s.htsi_band != "Normal").mean(), 100 * s.ushma.mean()]
    lbl = ["supplied notebook\n\"Red\" days", "USHMA\nWatch+", "USHMA\nWarning+"]
    b = ax[2].bar(lbl, vals, color=[S2, "#86b6ef", S1], width=0.6)
    for r, v in zip(b, vals):
        ax[2].text(r.get_x() + r.get_width() / 2, v + 1.2, f"{v:.1f}%", ha="center", fontsize=9, fontweight="bold")
    ax[2].set_ylabel("% of March–June days flagged"); ax[2].set_ylim(0, 58); ax[2].grid(axis="y", color=GRID); ax[2].set_axisbelow(True)
    ax[2].set_title("(c) An alert that means something", loc="left", fontweight="bold")

    plt.tight_layout()
    out = ROOT / "reports" / "figures" / "impact_vs_temperature.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, bbox_inches="tight")
    print(f"wrote {out}  (panel c: {[round(v, 1) for v in vals]})")


if __name__ == "__main__":
    main()
