#!/usr/bin/env python3
"""Plot retained additive event-year-start strata; no accessibility recomputation."""
from pathlib import Path
import sys
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from transport_figure_common import (
    ROOT, BLUE, ORANGE, load_grid_and_boundaries, load_missing_origin_grid,
    panel_label, save_figure, write_values,
)
DECOMPOSITION = ROOT / "Results/tables/transport_d_event_stratum_summary.csv"
STEM = "fig5_coverage_margin_decomposition"

def main():
    grid, _ = load_grid_and_boundaries(valid_only=True)
    missing = load_missing_origin_grid()
    decomposition = pd.read_csv(DECOMPOSITION)
    fig, axes = plt.subplots(1, 3, figsize=(7.3, 2.9), constrained_layout=True)
    records = []
    metric_order = ["total_opportunity", "cross_city_opportunity", "coverage"]
    labels = ["Total opportunity", "Outside-origin-city", "Coverage"]
    for index, (ax, metric, label) in enumerate(zip(axes, metric_order, labels)):
        uncovered = float(decomposition[f"{metric}_baseline_uncovered"].sum())
        covered = float(decomposition[f"{metric}_baseline_covered"].sum())
        if metric == "coverage":
            uncovered *= 100
            covered *= 100
        values = [uncovered, covered]
        maximum = max(abs(v) for v in values)
        for y, value, color in zip([1, 0], values, [ORANGE, BLUE]):
            ax.barh(y, value, color=color, height=0.46)
            label_value = f"{value:+.3f}" if metric == "coverage" else f"{value:,.1f}"
            if value < 0:
                ax.text(0.05*maximum, y, label_value, va="center", fontsize=9)
            else:
                ax.text(value + 0.03*maximum, y, label_value, va="center", fontsize=9)
        ax.set_xlim(min(0, min(values))*1.25 - maximum*0.03, maximum*1.5)
        ax.set_ylim(-0.65, 1.9)
        ax.vlines(0, -0.5, 1.45, color="#777777", lw=0.6)
        ax.set_yticks([])
        ax.set_title(label, fontsize=10, pad=10)
        ax.set_xlabel("Percentage points" if metric == "coverage" else "Effective population", fontsize=9)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v/1000:g}k" if abs(v) >= 1000 else f"{v:g}"))
        ax.tick_params(labelsize=8)
        ax.spines["left"].set_visible(False)
        panel_label(ax, "abc"[index])
        total = uncovered + covered
        records.append({
            "metric": metric,
            "baseline_uncovered_cumulative_contribution": uncovered,
            "baseline_covered_cumulative_contribution": covered,
            "total": total,
            "baseline_uncovered_share_of_total": uncovered/total if abs(total)>1e-14 else None,
        })
    fig.legend(handles=[
        Patch(facecolor=ORANGE, label="Uncovered at event-year start"),
        Patch(facecolor=BLUE, label="Covered at event-year start"),
    ], loc="outside lower center", ncol=2, frameon=False, fontsize=9)
    save_figure(fig, STEM)
    write_values(STEM, {
        "valid_origin_count": int(len(grid)),
        "missing_walk_snap_count": int(len(missing)),
        "decomposition_rows": int(len(decomposition)),
        "decomposition_source": str(DECOMPOSITION.relative_to(ROOT)),
        "decomposition_scope": "sum of authoritative equal-city additive event contributions by event-year-start coverage state",
        "coverage_display_unit": "percentage points",
        "metrics": records,
    })

if __name__ == "__main__":
    main()
