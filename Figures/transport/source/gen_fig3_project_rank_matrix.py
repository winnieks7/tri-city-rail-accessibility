#!/usr/bin/env python3
"""Generate the all-event, three-metric project rank matrix."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from transport_figure_common import ROOT, event_code_map, save_figure, write_values  # noqa: E402


SOURCE = ROOT / "Results/tables/transport_d_project_summary.csv"
STEM = "fig3_project_rank_matrix"
SHORT_NAMES = ["GZ L3 Airport North","Qingtang station","Guangfo to Lijiao","GZ L14 main line","GZ L21 east","GZ L21 west","GZ L8 Cultural Park","Gaoming Tram opening","Huangpu Tram first","GZ L8 north","Guangqing / East Ring","Huangpu Tram completion","Nanhai Tram first","GZ L18 first","FS L2 phase 1","GZ L22 first","GZ L7 west","Rainbow Bridge station","Nanhai Tram completion","FS L3 first","Xicun station / transfer","GZ L5 east","GZ L7 phase 2","Four-line intercity","Gaoming Tram suspension","FS L3 two sections","GZ L3 east","Haizhu Tram closure","GZ L11 composite"]
METRICS = {
    "Total opportunity": "population_weighted_total_opportunity_contribution",
    "Outside-origin-city": "population_weighted_cross_city_opportunity_contribution",
    "Coverage": "population_weighted_coverage_contribution",
}


def format_value(metric: str, value: float) -> str:
    if abs(value) <= 1e-10:
        return "0"
    if metric == "Coverage":
        return f"{100 * value:+.3f} pp"
    if abs(value) >= 1000:
        return f"{value / 1000:+.1f}k"
    if abs(value) < 1:
        return f"{value:+.2f}"
    return f"{value:+.0f}"


def main() -> None:
    data = pd.read_csv(SOURCE)
    codes = event_code_map(data)
    data = data.sort_values(
        METRICS["Total opportunity"], ascending=False
    ).reset_index(drop=True)
    n = len(data)
    values = np.column_stack([data[column].to_numpy(dtype=float) for column in METRICS.values()])
    ranks = np.column_stack(
        [data[column].rank(method="min", ascending=False).to_numpy(dtype=float) for column in METRICS.values()]
    )
    rank_score = 1 - (ranks - 1) / (n - 1)

    fig, ax = plt.subplots(figsize=(7.3, 8.3), constrained_layout=True)
    image = ax.imshow(rank_score, cmap="cividis", vmin=0, vmax=1, aspect="auto")
    for row in range(n):
        for col, metric in enumerate(METRICS):
            value = values[row, col]
            colour = "white" if rank_score[row, col] < 0.60 else "#111111"
            ax.text(col, row, format_value(metric, value), ha="center", va="center", fontsize=8.5, color=colour)
            if value < -1e-10:
                ax.scatter(col + 0.37, row, marker="x", s=18, color="#D55E00", linewidth=0.9, zorder=5)
            elif abs(value) <= 1e-10:
                ax.scatter(col + 0.37, row, marker="o", s=13, facecolors="none", edgecolors="#6A6A6A", linewidth=0.8, zorder=5)
    ax.set_xticks(range(3), list(METRICS))
    ax.xaxis.tick_top()
    ax.tick_params(axis="x", length=0, pad=5)
    ax.set_yticks(
        range(n),
        [f"{codes[str(event_id)]}  {SHORT_NAMES[int(codes[str(event_id)][1:])-1]}" for event_id in data["event_id"]],
        fontsize=8.5,
    )
    ax.tick_params(axis="y", length=0, pad=3)
    ax.set_xticks(np.arange(-0.5, 3, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.55)
    ax.tick_params(which="minor", bottom=False, left=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    cbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.025)
    cbar.set_label("Within-metric rank score (1 = highest)")
    handles = [
        Line2D([0], [0], marker="x", color="none", markeredgecolor="#D55E00", label="Negative contribution", markersize=6),
        Line2D([0], [0], marker="o", color="none", markeredgecolor="#6A6A6A", markerfacecolor="none", label="Zero contribution", markersize=5),
    ]
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, -0.065), frameon=False, ncol=2)
    save_figure(fig, STEM)
    write_values(
        STEM,
        {
            "event_count": int(n),
            "sort_metric": "population_weighted_total_opportunity_contribution",
            "cell_labels": "raw contribution; opportunity values use effective population and coverage uses percentage points",
            "events": [
                {
                    "event_id": row.event_id,
                    "event_code": codes[str(row.event_id)],
                    "year": int(row.year),
                    "event_label": row.event_label,
                    "total_opportunity_contribution": float(getattr(row, METRICS["Total opportunity"])),
                    "cross_city_opportunity_contribution": float(getattr(row, METRICS["Outside-origin-city"])),
                    "coverage_contribution": float(getattr(row, METRICS["Coverage"])),
                    "total_opportunity_rank": int(ranks[index, 0]),
                    "cross_city_opportunity_rank": int(ranks[index, 1]),
                    "coverage_rank": int(ranks[index, 2]),
                }
                for index, row in enumerate(data.itertuples(index=False))
            ],
            "zero_contribution_tolerance": 1e-10,
        },
    )


if __name__ == "__main__":
    main()
