#!/usr/bin/env python3
"""Generate R0-versus-sensitivity project contribution comparisons."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from matplotlib.ticker import FuncFormatter


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from transport_figure_common import BLUE, RED, ROOT, panel_label, save_figure, write_values  # noqa: E402


R2 = ROOT / "Results/tables/transport_d_r0_r2_comparison.csv"
R3 = ROOT / "Results/tables/transport_d_r0_r3_comparison.csv"
ONE_KM = ROOT / "Results/tables/transport_d_500m_1km_comparison.csv"
ONE_KM_AUDIT = ROOT / "Results/pilots/transport_d_1km_aggregation_sensitivity_audit.json"
STEM = "fig6_sensitivity_comparisons"
METRICS = ["total_opportunity", "cross_city_opportunity", "coverage"]
LABELS = ["Total opportunity", "Outside-origin-city", "Coverage"]
DISPLAY_MULTIPLIER = {"total_opportunity": 1.0, "cross_city_opportunity": 1.0, "coverage": 100.0}
DISPLAY_TICKS = {
    "total_opportunity": [-1e3, 0, 1e3, 1e4],
    "cross_city_opportunity": [-1e2, 0, 1e2, 1e3],
    "coverage": [-0.1, 0, 0.1, 1.0],
}


def wide_variant(path: Path, suffix: str) -> dict[str, pd.DataFrame]:
    data = pd.read_csv(path)
    output = {}
    for metric in METRICS:
        base = f"population_weighted_{metric}_contribution"
        output[metric] = pd.DataFrame(
            {
                "event_id": data["event_id"],
                "r0": data[f"{base}_r0"],
                "variant": data[f"{base}_{suffix}"],
                "sign_match": data[f"{metric}_sign_match"].astype(bool),
            }
        )
    return output


def kilometre_variant() -> dict[str, pd.DataFrame]:
    data = pd.read_csv(ONE_KM)
    mapping = {
        "total_opportunity": "total_opportunity_contribution",
        "cross_city_opportunity": "cross_city_opportunity_contribution",
        "coverage": "coverage_contribution",
    }
    output = {}
    for metric, source_metric in mapping.items():
        subset = data.loc[data["metric"].eq(source_metric)].copy()
        output[metric] = pd.DataFrame(
            {
                "event_id": subset["event_id"],
                "r0": subset["value_500m_full_support"],
                "variant": subset["value_1km_complete_parent_support"],
                "sign_match": subset["sign_500m"].eq(subset["sign_1km"]),
            }
        )
    return output


def symlog_threshold(values: np.ndarray) -> float:
    nonzero = np.abs(values[np.abs(values) > 1e-14])
    return max(float(np.percentile(nonzero, 15)) * 0.5, float(nonzero.max()) * 1e-6) if len(nonzero) else 1.0


def main() -> None:
    variants = [wide_variant(R2, "r2"), wide_variant(R3, "r3"), kilometre_variant()]
    support = json.loads(ONE_KM_AUDIT.read_text(encoding="utf-8"))["support"]
    retained_valid_population = float(support["valid_population_fraction_retained"])
    variant_labels = [
        "Conservative impedance",
        "Alternative connector",
        "Complete-parent support restriction",
    ]
    shared_scales = {}
    for metric in METRICS:
        combined = np.concatenate(
            [
                np.concatenate(
                    [variant[metric]["r0"].to_numpy(dtype=float), variant[metric]["variant"].to_numpy(dtype=float)]
                )
                for variant in variants
            ]
        )
        lower = float(np.nanmin(combined))
        upper = float(np.nanmax(combined))
        padding = 0.06 * max(upper - lower, 1e-12)
        multiplier = DISPLAY_MULTIPLIER[metric]
        shared_scales[metric] = {
            "lower": (lower - padding) * multiplier,
            "upper": (upper + padding) * multiplier,
            "linear_threshold": symlog_threshold(combined) * multiplier,
        }
    fig, axes = plt.subplots(3, 3, figsize=(7.3, 6.8))
    fig.subplots_adjust(left=0.095, right=0.98, bottom=0.10, top=0.91, wspace=0.30, hspace=0.15)
    records = []
    letters = list("abcdefghi")
    for row, (variant, variant_label) in enumerate(zip(variants, variant_labels)):
        for col, (metric, metric_label) in enumerate(zip(METRICS, LABELS)):
            ax = axes[row, col]
            data = variant[metric]
            multiplier = DISPLAY_MULTIPLIER[metric]
            display_reference = data["r0"] * multiplier
            display_variant = data["variant"] * multiplier
            match = data["sign_match"].to_numpy(dtype=bool)
            ax.scatter(display_reference.loc[match], display_variant.loc[match], s=19, color=BLUE, alpha=0.78, edgecolor="white", linewidth=0.25)
            if (~match).any():
                ax.scatter(display_reference.loc[~match], display_variant.loc[~match], s=34, facecolors="none", edgecolors=RED, linewidth=1.0, zorder=5)
            scale = shared_scales[metric]
            lo, hi = scale["lower"], scale["upper"]
            ax.plot([lo, hi], [lo, hi], color="#555555", linewidth=0.75, linestyle="--")
            threshold = scale["linear_threshold"]
            ax.set_xscale("symlog", linthresh=threshold)
            ax.set_yscale("symlog", linthresh=threshold)
            ax.set_xlim(lo, hi)
            ax.set_ylim(lo, hi)
            visible_ticks = [tick for tick in DISPLAY_TICKS[metric] if lo <= tick <= hi]
            ax.set_xticks(visible_ticks)
            ax.set_yticks(visible_ticks)
            formatter = FuncFormatter(lambda v, _: f"{v/1000:g}k" if abs(v) >= 1000 else f"{v:g}")
            ax.xaxis.set_major_formatter(formatter)
            ax.yaxis.set_major_formatter(formatter)
            rho = float(spearmanr(data["r0"], data["variant"]).statistic)
            sign_n = int(match.sum())
            cumulative_ratio = float(data["variant"].sum() / data["r0"].sum())
            ax.text(
                0.04,
                0.82,
                f"ρ = {rho:.3f}; signs {sign_n}/29\nΣ ratio = {cumulative_ratio:.3f}",
                transform=ax.transAxes,
                ha="left",
                va="top",
                fontsize=8,
            )
            panel_label(ax, letters[row * 3 + col])
            if row == 0:
                ax.set_xlabel(metric_label + ("\n(percentage points)" if metric == "coverage" else "\n(effective population)"), labelpad=8)
                ax.xaxis.set_label_position("top")
            elif row == 2:
                ax.set_xlabel("Reference contribution")
            if col == 0:
                ax.set_ylabel(
                    ["Conservative impedance", "Alternative connector", "Complete-parent support"][row]
                )
            ax.tick_params(labelsize=8, labelbottom=(row == 2))
            ax.grid(False)
            records.append(
                {
                    "panel": letters[row * 3 + col],
                    "variant": variant_label,
                    "metric": metric,
                    "spearman": rho,
                    "sign_agreement_n": sign_n,
                    "event_count": int(len(data)),
                    "sign_disagreement_event_ids": data.loc[~match, "event_id"].tolist(),
                    "symlog_linear_threshold": threshold,
                    "shared_axis_limits_for_metric": [lo, hi],
                    "display_unit": "percentage points" if metric == "coverage" else "effective population",
                    "source_to_display_multiplier": multiplier,
                    "cumulative_variant_to_reference_ratio": cumulative_ratio,
                }
            )
    save_figure(fig, STEM)
    write_values(
        STEM,
        {
            "panels": records,
            "identity_line": True,
            "red_open_markers": "events whose sign differs from R0/500m",
            "replication_unit": "29 frozen event packages; sensitivity variants are deterministic diagnostics, not independent replications",
            "complete_parent_support_restriction": {
                "valid_population_fraction_retained": retained_valid_population,
                "interpretation": "difference from full-support R0 is driven by support restriction; within the retained support, 500 m to 1 km aggregation closes to numerical precision",
            },
        },
    )


if __name__ == "__main__":
    main()
