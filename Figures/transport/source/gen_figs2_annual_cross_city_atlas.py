#!/usr/bin/env python3
"""Generate the 2017–2024 outside-origin-city-opportunity atlas."""

from transport_figure_common import plot_annual_atlas


if __name__ == "__main__":
    plot_annual_atlas(
        "cross_city_opportunity",
        "figs2_annual_cross_city_atlas",
        "log1p outside-origin-city effective population",
    )
