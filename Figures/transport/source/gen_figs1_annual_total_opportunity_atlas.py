#!/usr/bin/env python3
"""Generate the 2017–2024 total-opportunity atlas."""

from transport_figure_common import plot_annual_atlas


if __name__ == "__main__":
    plot_annual_atlas(
        "total_opportunity",
        "figs1_annual_total_opportunity_atlas",
        "log1p total effective population",
    )
