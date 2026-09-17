#!/usr/bin/env python3
"""Generate the tri-city scope and rail-topology evolution map."""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from transport_figure_common import (  # noqa: E402
    BLACK,
    BLUE,
    CITIES,
    GREY,
    LIGHT_GREY,
    ORANGE,
    ROOT,
    add_north_arrow,
    add_scale_bar,
    load_grid_and_boundaries,
    panel_label,
    raster_spec,
    save_figure,
    write_values,
)


TRACKS = ROOT / "Data/interim/transport/d_annual_active_track_edges.parquet"
STEM = "fig1_tri_city_network_evolution"


def clean_axis(ax, bounds) -> None:
    xmin, ymin, xmax, ymax = bounds
    padx = 0.035 * (xmax - xmin)
    pady = 0.035 * (ymax - ymin)
    ax.set_xlim(xmin - padx, xmax + padx)
    ax.set_ylim(ymin - pady, ymax + pady)
    ax.set_aspect("equal")
    ax.set_axis_off()


def label_target_cities(ax, cities) -> None:
    labels = {"Guangzhou": "GZ", "Foshan": "FS", "Dongguan": "DG"}
    for row in cities.loc[cities["gba_city"].isin(labels)].itertuples(index=False):
        point = row.geometry.representative_point()
        ax.text(
            point.x,
            point.y,
            labels[row.gba_city],
            fontsize=8,
            ha="center",
            va="center",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 1.0, "pad": 0.9},
            zorder=20,
        )


def main() -> None:
    grid, cities = load_grid_and_boundaries(valid_only=True)
    spec = raster_spec(grid)
    tracks = gpd.read_parquet(TRACKS).to_crs(grid.crs)
    keys = ["sequence_id", "route_identity", "from_order", "to_order"]
    year2017 = tracks.loc[tracks["year"].eq(2017)].drop_duplicates(keys)
    year2024 = tracks.loc[tracks["year"].eq(2024)].drop_duplicates(keys)
    first_year = tracks.groupby(keys, as_index=False)["year"].min().rename(columns={"year": "first_active_year"})
    first_geometry = tracks.sort_values("year").drop_duplicates(keys)
    additions = first_geometry.merge(first_year, on=keys, validate="one_to_one")
    additions = gpd.GeoDataFrame(additions, geometry="geometry", crs=tracks.crs)
    additions = additions.loc[additions["first_active_year"].gt(2017)]
    target = cities.loc[cities["gba_city"].isin(["Guangzhou", "Foshan", "Dongguan"])]
    context = cities.loc[~cities["gba_city"].isin(["Hong Kong", "Macao"])]

    fig, axes = plt.subplots(1, 3, figsize=(7.3, 3.4), constrained_layout=True)
    context.plot(ax=axes[0], facecolor="#F2F2F2", edgecolor="white", linewidth=0.45)
    extra_dest = context.loc[context["gba_city"].isin(["Huizhou", "Zhaoqing"])]
    extra_dest.plot(ax=axes[0], facecolor="#E1EED9", edgecolor="white", linewidth=0.45)
    target.plot(ax=axes[0], facecolor="#CFE8F3", edgecolor=BLACK, linewidth=0.65)
    year2024.plot(ax=axes[0], color=BLUE, linewidth=0.38, alpha=0.9)
    clean_axis(axes[0], tuple(context.total_bounds))
    label_target_cities(axes[0], cities)
    panel_label(axes[0], "a")

    target.plot(ax=axes[1], facecolor="#F7F7F7", edgecolor=BLACK, linewidth=0.55)
    year2017.plot(ax=axes[1], color=GREY, linewidth=0.55)
    clean_axis(axes[1], tuple(target.total_bounds))
    label_target_cities(axes[1], cities)
    panel_label(axes[1], "b")
    add_scale_bar(axes[1], spec, 25)
    add_north_arrow(axes[1])

    target.plot(ax=axes[2], facecolor="#F7F7F7", edgecolor=BLACK, linewidth=0.55)
    year2017.plot(ax=axes[2], color=LIGHT_GREY, linewidth=0.42)
    year_colours = {
        2018: "#0072B2",
        2019: "#009E73",
        2020: "#D55E00",
        2021: "#CC79A7",
        2022: "#56B4E9",
        2023: "#A45A00",
        2024: "#111111",
    }
    year_styles = {
        2018: "solid",
        2019: (0, (5, 1.5)),
        2020: (0, (1.2, 1.2)),
        2021: (0, (5, 1.2, 1.2, 1.2)),
        2022: (0, (3, 1.2)),
        2023: (0, (2, 1.1, 1, 1.1)),
        2024: (0, (7, 1.4)),
    }
    for year in range(2018, 2025):
        subset = additions.loc[additions["first_active_year"].eq(year)]
        subset.plot(
            ax=axes[2],
            color=year_colours[year],
            linewidth=0.95,
            linestyle=year_styles[year],
        )
    clean_axis(axes[2], tuple(target.total_bounds))
    label_target_cities(axes[2], cities)
    panel_label(axes[2], "c")
    handles = [Line2D([0], [0], color=LIGHT_GREY, lw=1.4, label="Active in 2017")]
    handles.extend(
        Line2D(
            [0],
            [0],
            color=year_colours[year],
            lw=1.8,
            linestyle=year_styles[year],
            label=str(year),
        )
        for year in range(2018, 2025)
    )
    fig.legend(
        handles=handles,
        loc="outside lower center",
        frameon=False,
        ncol=4,
        fontsize=8,
        handlelength=1.6,
        columnspacing=0.8,
    )

    for ax, title in zip(axes, ["Study domains", "2017 baseline", "2018–2024 activations"]):
        ax.set_title(title, fontsize=9, pad=7)
    fig._transport_alignment_options = {"exemptions": [{"panels": ["a"], "checks": ["row", "panel-label"], "reason": "Context map preserves a different geographic aspect ratio; panels b/c share the tri-city extent."}]}
    save_figure(fig, STEM)
    write_values(
        STEM,
        {
            "valid_origin_cells": int(len(grid)),
            "target_cities": ["Guangzhou", "Foshan", "Dongguan"],
            "active_route_sequence_arcs_2017": int(len(year2017)),
            "active_route_sequence_arcs_2024": int(len(year2024)),
            "route_sequence_arcs_first_activated_2018_2024": int(len(additions)),
            "first_activation_route_sequence_arc_counts": {
                str(year): int(additions["first_active_year"].eq(year).sum())
                for year in range(2018, 2025)
            },
            "counting_unit": "route-sequence adjacent-station arc keyed by sequence_id, route_identity, from_order and to_order; not a physically unique track segment",
            "note": "First modeled activation is shown even if an arc was later suspended; topology derives from archived OSM track relations and frozen event rules.",
        },
    )


if __name__ == "__main__":
    main()
