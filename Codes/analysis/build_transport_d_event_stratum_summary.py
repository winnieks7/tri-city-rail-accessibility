#!/usr/bin/env python3
"""Build the authoritative additive event-by-baseline-stratum result chain."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "Results/tables/transport_d_baseline_coverage_decomposition.csv"
LEGACY = ROOT / "Results/tables/transport_d_project_summary.csv"
OUTPUT = ROOT / "Results/tables/transport_d_event_stratum_summary.csv"
AUDIT = ROOT / "Results/pilots/transport_d_event_stratum_summary_audit.json"
TOLERANCE = 1e-9

METRIC_TO_LEGACY_TOTAL = {
    "total_opportunity": "population_weighted_total_opportunity_contribution",
    "cross_city_opportunity": "population_weighted_cross_city_opportunity_contribution",
    "coverage": "population_weighted_coverage_contribution",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    source = pd.read_csv(SOURCE)
    source = source.loc[source["geography"].eq("D_equal_city")].copy()
    legacy = pd.read_csv(LEGACY)
    base = (
        source[["event_id", "year", "event_label"]]
        .drop_duplicates()
        .sort_values(["year", "event_id"])
        .reset_index(drop=True)
    )
    output = base.copy()
    closure_rows = []
    for metric, legacy_column in METRIC_TO_LEGACY_TOTAL.items():
        metric_rows = source.loc[source["metric"].eq(metric)]
        pivot = metric_rows.pivot(
            index="event_id",
            columns="baseline_stratum",
            values="additive_population_weighted_contribution",
        )
        totals = metric_rows.groupby("event_id")[
            "full_population_weighted_contribution"
        ].first()
        output[f"{metric}_baseline_uncovered"] = output["event_id"].map(
            pivot["baseline_uncovered"]
        )
        output[f"{metric}_baseline_covered"] = output["event_id"].map(
            pivot["baseline_covered"]
        )
        output[f"{metric}_total"] = output["event_id"].map(totals)
        output[f"{metric}_closure_error"] = (
            output[f"{metric}_baseline_uncovered"]
            + output[f"{metric}_baseline_covered"]
            - output[f"{metric}_total"]
        )
        legacy_total = legacy.set_index("event_id")[legacy_column]
        output[f"{metric}_legacy_total_match_error"] = (
            output[f"{metric}_total"]
            - output["event_id"].map(legacy_total)
        )
        for row in output.itertuples(index=False):
            closure_rows.append(
                {
                    "event_id": row.event_id,
                    "metric": metric,
                    "closure_error": getattr(row, f"{metric}_closure_error"),
                    "legacy_total_match_error": getattr(
                        row, f"{metric}_legacy_total_match_error"
                    ),
                }
            )

    numeric_columns = [
        column
        for column in output.columns
        if column not in {"event_id", "year", "event_label"}
    ]
    output[numeric_columns] = output[numeric_columns].astype(float)
    closure = pd.DataFrame(closure_rows)
    max_closure = float(closure["closure_error"].abs().max())
    max_legacy_match = float(closure["legacy_total_match_error"].abs().max())
    cumulative = {
        metric: {
            "baseline_uncovered": float(
                output[f"{metric}_baseline_uncovered"].sum()
            ),
            "baseline_covered": float(
                output[f"{metric}_baseline_covered"].sum()
            ),
            "total": float(output[f"{metric}_total"].sum()),
        }
        for metric in METRIC_TO_LEGACY_TOTAL
    }
    for values in cumulative.values():
        values["closure_error"] = (
            values["baseline_uncovered"]
            + values["baseline_covered"]
            - values["total"]
        )
    checks = {
        "exactly_29_events": len(output) == 29,
        "three_metrics_present": len(METRIC_TO_LEGACY_TOTAL) == 3,
        "all_87_event_metric_rows_close": max_closure <= TOLERANCE,
        "all_authoritative_totals_match_frozen_event_totals": max_legacy_match
        <= TOLERANCE,
        "no_missing_numeric_values": not output[numeric_columns].isna().any().any(),
        "cumulative_add_back_closes": all(
            abs(values["closure_error"]) <= TOLERANCE
            for values in cumulative.values()
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT, index=False)
    audit = {
        "audit": "transport_D_authoritative_event_stratum_result_chain",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "estimand": (
            "within-city stratum numerators divided by the same full valid city "
            "population denominator, followed by an equal mean across the three cities"
        ),
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": sha256(SOURCE),
        "legacy_summary": str(LEGACY.relative_to(ROOT)),
        "legacy_summary_sha256": sha256(LEGACY),
        "legacy_field_boundary": (
            "legacy uncovered/covered fields use stratum-specific denominators and are "
            "not additive; they are deprecated for Equation 10, Figure 5, and RQ3"
        ),
        "authoritative_output": str(OUTPUT.relative_to(ROOT)),
        "authoritative_output_sha256": sha256(OUTPUT),
        "counts": {"events": len(output), "event_metric_closures": len(closure)},
        "tolerance": TOLERANCE,
        "maximum_absolute_event_metric_closure_error": max_closure,
        "maximum_absolute_legacy_total_match_error": max_legacy_match,
        "cumulative_equal_city": cumulative,
        "checks": checks,
        "passed": all(checks.values()),
    }
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
