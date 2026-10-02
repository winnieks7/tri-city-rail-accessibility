#!/usr/bin/env python3
"""Render all 29 retained event plates at print width; keep P29's local detail."""

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
sys.path.insert(0, str(HERE.parents[3]))
from Codes.analysis.transport_event_state import FrozenEventStateBuilder
from transport_figure_common import (  # noqa: E402
    CONTRIBUTION,
    WIDTH,
    audit_alignment,
    SVG_DIR,
    signed_colorbar_ticks,
    DIVERGING,
    ROOT,
    SUPP_DIR,
    QA_DIR,
    p29_local_detail,
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
    QA_DIR.mkdir(parents=True, exist_ok=True)
    output = SUPP_DIR / f"{STEM}.pdf"
    pages = []
    with PdfPages(output) as pdf:
        for page_index, event in events.iterrows():
            is_p29 = codes[str(event["event_id"])] == "P29"
            fig, axes = plt.subplots(1, 3, figsize=(WIDTH, (141 if is_p29 else 85)/25.4))
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
                # Municipal names belong in quiet interiors, away from the
                # event tracks. Positions are label anchors, not observations.
                for text in ax.texts:
                    if text.get_text() == "GZ":
                        text.set_position((12780.555086261113, 45727.750736635906))
                    elif text.get_text() == "FS":
                        text.set_position((-58935.44910117815, 27404.839174729463))
                ax.set_position([0.018+panel_index*0.331, 0.58 if is_p29 else 0.29,
                                 0.292, 0.32 if is_p29 else 0.53])
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
                    fontsize=7,
                )
                cax = fig.add_axes([0.028+panel_index*0.331, 0.517 if is_p29 else 0.195,
                                   0.272, 0.010 if is_p29 else 0.017])
                cbar = fig.colorbar(image, cax=cax, orientation="horizontal")
                signed_colorbar_ticks(cbar, norm)
                cbar.set_label(unit, fontsize=6.5, labelpad=1.5)
                cbar.ax.tick_params(labelsize=6, pad=1)
                if panel_index == 0:
                    add_scale_bar(ax, spec)
                    add_north_arrow(ax)
                    if is_p29:
                        _, detail_record = p29_local_detail(
                            fig, ax, grid, values, spec, cities, missing, norm,
                            [0.10, 0.125, 0.80, 0.295], letter="d")

            handles = event_topology_legend_handles() + [
                Patch(facecolor="white", edgecolor="#B0B0B0", label="Outside valid origin grid"),
                Patch(facecolor="#F7F7F7", edgecolor="#B0B0B0", label="Zero contribution"),
            ]
            fig.legend(
                handles=handles,
                loc="lower center",
                bbox_to_anchor=(0.5, 0.015),
                ncol=4,
                frameon=False,
                fontsize=6,
                columnspacing=1.1,
                handlelength=1.5,
            )
            fig.text(
                0.5,
                0.975,
                f"{codes[str(event['event_id'])]}  |  {int(event['year'])}  |  {event['event_label']}",
                ha="center",
                va="top",
                fontsize=7,
                fontweight="bold",
            )
            audit_alignment(fig, f"{STEM}_{codes[str(event['event_id'])]}")
            svg_output = SVG_DIR / "supplementary/figs7_event_detail_atlas_pages"
            svg_output.mkdir(parents=True, exist_ok=True)
            fig.savefig(svg_output / f"{STEM}_{codes[str(event['event_id'])]}.svg")
            pdf.savefig(fig)
            fig.savefig(QA_DIR / f"{STEM}_{codes[str(event['event_id'])]}.png", dpi=300)
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
            "local_enlargement": detail_record,
            "scope": "All 29 event plates; retained allocations and topology; P29 all-sign detail preserved",
        },
    )


if __name__ == "__main__":
    main()
