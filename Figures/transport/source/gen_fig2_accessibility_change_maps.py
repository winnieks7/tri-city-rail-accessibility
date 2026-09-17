#!/usr/bin/env python3
"""Generate 2017, 2024 and change maps for the three primary metrics."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, ListedColormap


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from transport_figure_common import (  # noqa: E402
    ANNUAL,
    DIVERGING,
    add_scale_bar,
    add_north_arrow,
    annual_level_limit,
    format_map_axis,
    load_grid_and_boundaries,
    load_missing_origin_grid,
    mark_missing_origins,
    panel_label,
    raster_spec,
    rasterize,
    save_figure,
    signed_norm,
    values_on_grid,
    write_values,
)


STEM = "fig2_accessibility_change_maps"
METRICS = ["total_opportunity", "cross_city_opportunity", "coverage"]


def main() -> None:
    grid, cities = load_grid_and_boundaries(valid_only=True)
    missing = load_missing_origin_grid()
    spec = raster_spec(grid)
    annual = pd.read_parquet(
        ANNUAL,
        columns=["grid_id", "analysis_status", "year", *METRICS],
    )
    annual = annual.loc[
        annual["analysis_status"].ne("missing_walk_snap")
        & annual["year"].isin([2017, 2024])
    ]
    by_year = {
        year: annual.loc[annual["year"].eq(year)].set_index("grid_id")
        for year in [2017, 2024]
    }
    fig, axes = plt.subplots(3, 3, figsize=(7.3, 7.1))
    plotted = {}
    letters = list("abcdefghi")
    colour_limits = {}
    for row, metric in enumerate(METRICS):
        start = by_year[2017][metric].reindex(grid["grid_id"]).to_numpy(dtype=float)
        end = by_year[2024][metric].reindex(grid["grid_id"]).to_numpy(dtype=float)
        change = end - start
        if metric == "coverage":
            level_cmap = ListedColormap(["#E8EEF1", "#0072B2"])
            level_norm = BoundaryNorm([-0.5, 0.5, 1.5], 2)
            change_cmap = plt.get_cmap("PuOr", 3)
            change_norm = BoundaryNorm([-1.5, -0.5, 0.5, 1.5], change_cmap.N)
            level_label = "Coverage"
            change_label = "Coverage change"
            colour_limits[metric] = {"level": [0, 1], "change": [-1, 1]}
        else:
            upper = annual_level_limit(metric)
            level_cmap = "viridis"
            level_norm = plt.Normalize(0, upper)
            change_norm, limit, linthresh = signed_norm(change, percentile=99.5)
            change_cmap = DIVERGING
            level_label = "log1p effective population"
            change_label = "Effective population change"
            colour_limits[metric] = {
                "level_log1p_upper": upper,
                "change_absolute_limit": limit,
                "change_linear_threshold": linthresh,
            }
            start = np.log1p(np.clip(start, 0, None))
            end = np.log1p(np.clip(end, 0, None))
        values_list = [start, end, change]
        images = []
        for col, values in enumerate(values_list):
            cmap = level_cmap if col < 2 else change_cmap
            norm = level_norm if col < 2 else change_norm
            image = axes[row, col].imshow(
                rasterize(grid, values, spec),
                origin="lower",
                extent=spec["extent"],
                cmap=cmap,
                norm=norm,
                interpolation="nearest",
                rasterized=True,
            )
            format_map_axis(axes[row, col], cities, spec, city_labels=(col == 0))
            if row == 0 and col == 0:
                add_scale_bar(axes[row, col], spec)
                add_north_arrow(axes[row, col])
            mark_missing_origins(axes[row, col], missing)
            panel_label(axes[row, col], letters[row * 3 + col])
            axes[row, col].set_position([0.075 + col * 0.31, 0.735 - row * 0.32, 0.265, 0.22])
            images.append(image)
            plotted[letters[row * 3 + col]] = {
                "metric": metric,
                "display": ["2017", "2024", "2024_minus_2017"][col],
            }
        for index, (left, width, source, label) in enumerate([(0.075, 0.575, images[0], level_label), (0.695, 0.265, images[2], change_label)]):
            cax = fig.add_axes([left, 0.703-row*0.32, width, 0.015])
            cbar = fig.colorbar(source, cax=cax, orientation="horizontal")
            cbar.set_label(label, fontsize=8, labelpad=2)
            cbar.ax.tick_params(labelsize=8, pad=1)
            if metric != "coverage" and index == 1:
                ticks = [source.norm.vmin, 0, source.norm.vmax]
                cbar.set_ticks(ticks)
                cbar.set_ticklabels([f"{v/1e6:.2g}M" if abs(v)>=1e6 else f"{v/1e3:.3g}k" if abs(v)>=1e3 else f"{v:g}" for v in ticks])
            if metric == "coverage":
                cbar.set_ticks([0, 1] if index == 0 else [-1, 0, 1])
                cbar.set_ticklabels(["Uncovered", "Covered"] if index == 0 else ["Loss", "No change", "Gain"])
                cbar.ax.tick_params(length=0)
    for ax, title in zip(axes[0], ["2017", "2024", "Change (2024 − 2017)"]):
        ax.set_title(title, fontsize=9, pad=10)
    for ax, label in zip(axes[:, 0], ["Total opportunity", "Outside-origin-city opportunity", "Station-access coverage"]):
        ax.text(-0.09, 0.5, label, rotation=90, transform=ax.transAxes, ha="right", va="center", fontsize=9)
    save_figure(fig, STEM)
    write_values(
        STEM,
        {
            "valid_origin_count": int(len(grid)),
            "missing_walk_snap_count": int(len(missing)),
            "missing_origin_display": "grey x; excluded from summaries",
            "structural_zero_display": "valid zero retained in the colour scale",
            "panels": plotted,
            "colour_limits": colour_limits,
            "level_display_transform": {"total_opportunity": "log1p", "cross_city_opportunity": "log1p", "coverage": "none"},
            "opportunity_level_colour_limit_percentile": 99.5,
            "opportunity_change_colour_limit_percentile": 99.5,
            "coverage_colour_limit_percentile": None,
        },
    )


if __name__ == "__main__":
    main()
