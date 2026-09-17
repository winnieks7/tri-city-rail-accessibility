#!/usr/bin/env python3
"""Generate all 29 total-opportunity contribution maps."""

from transport_figure_common import plot_project_atlas


if __name__ == "__main__":
    plot_project_atlas(
        "total_opportunity_contribution",
        "figs4_all_project_total_atlas",
        "Total-opportunity contribution",
    )
