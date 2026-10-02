#!/usr/bin/env python3
"""Generate all 29 outside-origin-city-opportunity contribution maps."""

from transport_figure_common import plot_project_atlas


if __name__ == "__main__":
    plot_project_atlas(
        "cross_city_opportunity_contribution",
        "figs5_all_project_cross_city_atlas",
        "Outside-origin-city-opportunity contribution",
    )
