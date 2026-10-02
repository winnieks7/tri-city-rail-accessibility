#!/usr/bin/env python3
"""Generate the 2017–2024 modeled-coverage atlas."""

from transport_figure_common import plot_annual_atlas


if __name__ == "__main__":
    plot_annual_atlas(
        "coverage",
        "figs3_annual_coverage_atlas",
        "Modeled coverage (0/1)",
    )
