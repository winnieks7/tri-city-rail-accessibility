#!/usr/bin/env python3
"""Generate a legible 29-page event atlas with all metrics and topology overlays."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Patch


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
from Codes.analysis.transport_event_state import FrozenEventStateBuilder
from transport_figure_common import (  # noqa: E402
    CONTRIBUTION,
    audit_alignment,
    SVG_DIR,
    signed_colorbar_ticks,
    DIVERGING,
    ROOT,
    SUPP_DIR,
    add_north_arrow,
    add_scale_bar,
    event_code_map,
    event_topology_change,
    event_topology_legend_handles,
    format_map_axis,
    load_grid_and_boundaries,
    load_missing_origin_grid,
    mark_missing_origins,
    panel_label,
    plot_event_topology_change,
    raster_spec,
    rasterize,
    signed_norm,
    values_on_grid,
    write_values,
)


STEM = "figs7_event_detail_atlas"
METRICS = [
    ("total_opportunity_contribution", "Total opportunity", "Effective population"),
    (
        "cross_city_opportunity_contribution",
        "Outside-origin-city opportunity",
        "Effective population",
    ),
    ("coverage_contribution", "Station-access coverage", "Fraction"),
]


def main() -> None:
    grid, cities = load_grid_and_boundaries(valid_only=True)
    missing = load_missing_origin_grid()
    spec = raster_spec(grid)
    columns = [metric for metric, _, _ in METRICS]
    data = pd.read_parquet(
        CONTRIBUTION,
        columns=[
            "grid_id",
            "analysis_status",
            "event_id",
            "event_label",
            "year",
            *columns,
        ],
    )
    data = data.loc[data["analysis_status"].ne("missing_walk_snap")]
    events = (
        data[["event_id", "event_label", "year"]]
        .drop_duplicates()
        .sort_values(["year", "event_id"])
        .reset_index(drop=True)
    )
    codes = event_code_map(events)
    norms = {
        metric: signed_norm(data[metric].to_numpy(dtype=float), percentile=99.5)
        for metric in columns
    }
    builder = FrozenEventStateBuilder()
    SUPP_DIR.mkdir(parents=True, exist_ok=True)
    output = SUPP_DIR / f"{STEM}.pdf"
    pages = []
    with PdfPages(output) as pdf:
        for page_index, event in events.iterrows():
            fig, axes = plt.subplots(1, 3, figsize=(10.4, 4.65), constrained_layout=True)
            event_frame = data.loc[data["event_id"].eq(event["event_id"])]
            change = event_topology_change(builder, str(event["event_id"]), grid.crs)
            for panel_index, (ax, (metric, label, unit)) in enumerate(zip(axes, METRICS)):
                values = values_on_grid(grid, event_frame[["grid_id", metric]], metric)
                norm, _, _ = norms[metric]
                image = ax.imshow(
                    rasterize(grid, values, spec),
                    origin="lower",
                    extent=spec["extent"],
                    cmap=DIVERGING,
                    norm=norm,
                    interpolation="nearest",
                    rasterized=True,
                )
                format_map_axis(ax, cities, spec, city_labels=True)
                plot_event_topology_change(ax, change, linewidth=0.55, show_stops=(metric != "coverage_contribution"))
                mark_missing_origins(ax, missing)
                panel_label(ax, "abc"[panel_index])
                ax.text(
                    0.5,
                    -0.025,
                    label,
                    transform=ax.transAxes,
                    ha="center",
                    va="top",
                    fontsize=9.0,
                )
                cbar = fig.colorbar(image, ax=ax, fraction=0.038, pad=0.012)
                signed_colorbar_ticks(cbar, norm)
                cbar.set_label(unit, fontsize=8)
                cbar.ax.tick_params(labelsize=8)
                if panel_index == 0:
                    add_scale_bar(ax, spec)
                    add_north_arrow(ax)

            handles = event_topology_legend_handles() + [
                Patch(facecolor="white", edgecolor="#B0B0B0", label="Outside valid origin grid"),
                Patch(facecolor="#F7F7F7", edgecolor="#B0B0B0", label="Zero contribution"),
            ]
            fig.legend(
                handles=handles,
                loc="outside lower center",
                ncol=4,
                frameon=False,
                fontsize=8,
            )
            fig.text(
                0.5,
                0.995,
                f"{codes[str(event['event_id'])]}  |  {int(event['year'])}  |  {event['event_label']}",
                ha="center",
                va="top",
                fontsize=10,
                fontweight="bold",
            )
            audit_alignment(fig, f"{STEM}_{codes[str(event['event_id'])]}")
            svg_output = SVG_DIR / "supplementary/figs7_event_detail_atlas_pages"
            svg_output.mkdir(parents=True, exist_ok=True)
            fig.savefig(svg_output / f"{STEM}_{codes[str(event['event_id'])]}.svg")
            pdf.savefig(fig, bbox_inches="tight", pad_inches=0.05)
            if page_index == 0:
                fig.savefig(SUPP_DIR / f"{STEM}_preview.png", dpi=300)
            plt.close(fig)
            pages.append(
                {
                    "page": int(page_index + 1),
                    "event_code": codes[str(event["event_id"])],
                    "event_id": event["event_id"],
                    "year": int(event["year"]),
                    "event_label": event["event_label"],
                    "added_edge_count": int(len(change["added_edges"])),
                    "removed_edge_count": int(len(change["removed_edges"])),
                    "added_station_occurrence_count": int(len(change["added_stops"])),
                    "removed_station_occurrence_count": int(len(change["removed_stops"])),
                }
            )

    write_values(
        STEM,
        {
            "event_count": int(len(events)),
            "page_count": int(len(pages)),
            "output": str(output.relative_to(ROOT)),
            "valid_origin_count": int(len(grid)),
            "missing_walk_snap_count": int(len(missing)),
            "topology_overlay_definition": "event singleton versus event-year empty coalition; topology only",
            "normalization": "metric-specific global symmetric logarithmic scale shared across all 29 pages",
            "pages": pages,
        },
    )


if __name__ == "__main__":
    main()
