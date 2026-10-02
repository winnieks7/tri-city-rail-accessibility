#!/usr/bin/env python3
"""Generate all 29 coverage contribution maps."""

from transport_figure_common import plot_project_atlas


if __name__ == "__main__":
    plot_project_atlas(
        "coverage_contribution",
        "figs6_all_project_coverage_atlas",
        "Coverage contribution",
    )
