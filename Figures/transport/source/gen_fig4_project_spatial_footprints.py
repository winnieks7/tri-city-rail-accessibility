#!/usr/bin/env python3
"""Map the leading positive and most negative project footprint for each metric."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
from Codes.analysis.transport_event_state import FrozenEventStateBuilder
from transport_figure_common import (  # noqa: E402
    CONTRIBUTION,
    coverage_inset,
    DIVERGING,
    ROOT,
    add_scale_bar,
    add_north_arrow,
    event_topology_change,
    event_topology_legend_handles,
    event_code_map,
    format_map_axis,
    load_grid_and_boundaries,
    load_missing_origin_grid,
    mark_missing_origins,
    panel_label,
    plot_event_topology_change,
    raster_spec,
    rasterize,
    save_figure,
    signed_norm,
    values_on_grid,
    write_values,
)


SUMMARY = ROOT / "Results/tables/transport_d_project_summary.csv"
STEM = "fig4_project_spatial_footprints"
METRICS = {
    "total_opportunity_contribution": "population_weighted_total_opportunity_contribution",
    "cross_city_opportunity_contribution": "population_weighted_cross_city_opportunity_contribution",
    "coverage_contribution": "population_weighted_coverage_contribution",
}


def main() -> None:
    grid, cities = load_grid_and_boundaries(valid_only=True)
    missing = load_missing_origin_grid()
    spec = raster_spec(grid)
    summary = pd.read_csv(SUMMARY)
    state_builder = FrozenEventStateBuilder()
    codes = event_code_map(summary)
    contributions = pd.read_parquet(
        CONTRIBUTION,
        columns=["grid_id", "analysis_status", "event_id", "year", "event_label", *METRICS],
    )
    contributions = contributions.loc[contributions["analysis_status"].ne("missing_walk_snap")]
    selections = {}
    for cell_metric, summary_metric in METRICS.items():
        top = summary.loc[summary[summary_metric].idxmax()]
        bottom = summary.loc[summary[summary_metric].idxmin()]
        selections[cell_metric] = [top, bottom]

    fig, axes = plt.subplots(2, 3, figsize=(7.3, 5.3))
    letters = list("abcdef")
    panel_records = []
    metric_names = list(METRICS)
    for col, metric in enumerate(metric_names):
        selected_ids = [row["event_id"] for row in selections[metric]]
        selected_values = contributions.loc[
            contributions["event_id"].isin(selected_ids), metric
        ].to_numpy(dtype=float)
        norm, limit, linthresh = signed_norm(selected_values, percentile=99.5)
        images = []
        for row_index, event in enumerate(selections[metric]):
            frame = contributions.loc[
                contributions["event_id"].eq(event["event_id"]), ["grid_id", metric]
            ]
            values = values_on_grid(grid, frame, metric)
            image = axes[row_index, col].imshow(
                rasterize(grid, values, spec),
                origin="lower",
                extent=spec["extent"],
                cmap=DIVERGING,
                norm=norm,
                interpolation="nearest",
                rasterized=True,
            )
            images.append(image)
            format_map_axis(axes[row_index, col], cities, spec, city_labels=(col == 0))
            axes[row_index, col].set_position([0.025+col*0.33, 0.585-row_index*0.345, 0.29, 0.31])
            change = event_topology_change(
                state_builder, str(event["event_id"]), grid.crs
            )
            plot_event_topology_change(axes[row_index, col], change, show_stops=(col != 2))
            if col == 2:
                coverage_inset(axes[row_index, col], grid, values, spec, cities, norm)
            if row_index == 0 and col == 0:
                add_scale_bar(axes[row_index, col], spec)
                add_north_arrow(axes[row_index, col])
            mark_missing_origins(axes[row_index, col], missing)
            letter = letters[row_index * 3 + col]
            panel_label(axes[row_index, col], letter)
            axes[row_index, col].text(
                0.5,
                -0.025,
                codes[str(event["event_id"])],
                transform=axes[row_index, col].transAxes,
                ha="center",
                va="top",
                fontsize=8.5,
            )
            panel_records.append(
                {
                    "panel": letter,
                    "selection": "largest_positive" if row_index == 0 else "most_negative",
                    "metric": metric,
                    "event_id": event["event_id"],
                    "event_code": codes[str(event["event_id"])],
                    "year": int(event["year"]),
                    "event_label": event["event_label"],
                    "equal_city_population_weighted_contribution": float(event[METRICS[metric]]),
                    "absolute_colour_limit": limit,
                    "linear_threshold": linthresh,
                }
            )
        cax = fig.add_axes([0.04+col*0.33, 0.142, 0.26, 0.018])
        cbar = fig.colorbar(images[-1], cax=cax, orientation="horizontal")
        labels = {
            "total_opportunity_contribution": "Total-opportunity contribution",
            "cross_city_opportunity_contribution": "Outside-origin-city contribution",
            "coverage_contribution": "Coverage contribution",
        }
        cbar.set_label("Effective population" if col < 2 else "Fraction", fontsize=8)
        tick_values = [-limit, 0, limit]
        cbar.set_ticks(tick_values)
        cbar.set_ticklabels([f"{v:.2g}" for v in tick_values])
        cbar.ax.tick_params(labelsize=8)
    for ax, title in zip(axes[0], ["Total opportunity", "Outside-origin-city", "Coverage"]):
        ax.set_title(title, fontsize=9, pad=8)
    fig.legend(
        handles=event_topology_legend_handles(),
        loc="lower center",
        bbox_to_anchor=(0.5, -0.025),
        ncol=3,
        frameon=False,
        fontsize=8,
    )
    save_figure(fig, STEM)
    write_values(
        STEM,
        {
            "valid_origin_count": int(len(grid)),
            "missing_walk_snap_count": int(len(missing)),
            "missing_origin_display": "grey x; excluded from summaries",
            "zero_contribution_display": "valid zero retained near the neutral colour",
            "opportunity_unit": "effective population",
            "coverage_unit": "fraction",
            "selection_rule": "largest and smallest equal-city population-weighted contribution separately for each metric",
            "normalization": "column-specific symmetric logarithmic, 99.5th percentile absolute nonzero cell value",
            "panels": panel_records,
        },
    )


if __name__ == "__main__":
    main()
