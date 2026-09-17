#!/usr/bin/env python3
"""Cleanly replay paper-level summaries from the frozen cell outputs.

The script writes only below a new empty directory.  It does not reconstruct
network states or rerun the frozen accessibility attribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Codes.analysis.run_transport_d_project_attribution import build_summaries  # noqa: E402


ANNUAL_SOURCE = ROOT / "Data/processed/transport/d_annual_accessibility_cell.parquet"
EVENT_SOURCE = ROOT / "Data/processed/transport/d_project_attribution_cell.parquet"
EVENT_REFERENCE = ROOT / "Results/tables/transport_d_project_summary.csv"
STRATUM_REFERENCE = ROOT / "Results/tables/transport_d_event_stratum_summary.csv"
METRICS = ["total_opportunity", "cross_city_opportunity", "coverage"]
TOLERANCE = 1e-9


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def prepare_output(path: Path) -> Path:
    target = path.expanduser().resolve()
    if target == ROOT.resolve():
        raise RuntimeError("project root is not a replay output directory")
    if target.exists() and any(target.iterdir()):
        raise RuntimeError("derived replay output directory must be absent or empty")
    target.mkdir(parents=True, exist_ok=True)
    return target


def annual_summary(cells: pd.DataFrame) -> pd.DataFrame:
    records = []
    valid = cells.loc[cells["analysis_status"].ne("missing_walk_snap")].copy()
    for (year, city), group in valid.groupby(["year", "city"], sort=True):
        record = {"year": int(year), "geography": city}
        for metric in METRICS:
            record[f"population_weighted_{metric}"] = float(
                np.average(group[metric], weights=group["population_weight"])
            )
        records.append(record)
    city = pd.DataFrame(records)
    equal = city.groupby("year", as_index=False)[
        [f"population_weighted_{metric}" for metric in METRICS]
    ].mean()
    equal["geography"] = "D_equal_city"
    return pd.concat([city, equal], ignore_index=True).sort_values(
        ["year", "geography"]
    )


def additive_strata(contributions: pd.DataFrame) -> pd.DataFrame:
    valid = contributions.loc[
        contributions["analysis_status"].ne("missing_walk_snap")
    ].copy()
    rows = []
    contribution_columns = {
        metric: f"{metric}_contribution" for metric in METRICS
    }
    for (event_id, year, label), event in valid.groupby(
        ["event_id", "year", "event_label"], sort=True
    ):
        record = {
            "event_id": event_id,
            "year": int(year),
            "event_label": label,
        }
        city_records = []
        for _, city in event.groupby("city", sort=True):
            denominator = float(city["population_weight"].sum())
            city_record = {}
            for metric, column in contribution_columns.items():
                for stratum_name, baseline_value in (
                    ("baseline_uncovered", 0.0),
                    ("baseline_covered", 1.0),
                ):
                    selected = city.loc[city["baseline_coverage"].eq(baseline_value)]
                    city_record[f"{metric}_{stratum_name}"] = float(
                        (selected[column] * selected["population_weight"]).sum()
                        / denominator
                    )
                city_record[f"{metric}_total"] = float(
                    (city[column] * city["population_weight"]).sum() / denominator
                )
            city_records.append(city_record)
        for column in city_records[0]:
            record[column] = float(np.mean([item[column] for item in city_records]))
        for metric in METRICS:
            record[f"{metric}_closure_error"] = (
                record[f"{metric}_baseline_uncovered"]
                + record[f"{metric}_baseline_covered"]
                - record[f"{metric}_total"]
            )
        rows.append(record)
    return pd.DataFrame(rows).sort_values(["year", "event_id"])


def maximum_numeric_difference(
    replay: pd.DataFrame,
    reference: pd.DataFrame,
    keys: list[str],
    columns: list[str],
) -> float:
    merged = replay[keys + columns].merge(
        reference[keys + columns], on=keys, suffixes=("_replay", "_reference"),
        validate="one_to_one",
    )
    differences = [
        (merged[f"{column}_replay"] - merged[f"{column}_reference"]).abs().max()
        for column in columns
    ]
    return float(max(differences, default=0.0))


def main() -> int:
    output_dir = prepare_output(parse_args().output_dir)
    started = datetime.now(timezone.utc).isoformat()
    annual_cells = pd.read_parquet(ANNUAL_SOURCE)
    contributions = pd.read_parquet(EVENT_SOURCE)
    annual = annual_summary(annual_cells)
    _, event = build_summaries(contributions)
    strata = additive_strata(contributions)

    annual_path = output_dir / "replay_annual_city_summary.csv"
    event_path = output_dir / "replay_event_equal_city_summary.csv"
    strata_path = output_dir / "replay_event_stratum_summary.csv"
    annual.to_csv(annual_path, index=False)
    event.to_csv(event_path, index=False)
    strata.to_csv(strata_path, index=False)

    event_reference = pd.read_csv(EVENT_REFERENCE)
    event_columns = [
        f"population_weighted_{metric}_contribution" for metric in METRICS
    ] + [f"area_weighted_{metric}_contribution" for metric in METRICS]
    event_difference = maximum_numeric_difference(
        event,
        event_reference,
        ["event_id"],
        event_columns,
    )
    stratum_reference = pd.read_csv(STRATUM_REFERENCE)
    stratum_columns = [
        f"{metric}_{suffix}"
        for metric in METRICS
        for suffix in ("baseline_uncovered", "baseline_covered", "total")
    ]
    stratum_difference = maximum_numeric_difference(
        strata,
        stratum_reference,
        ["event_id"],
        stratum_columns,
    )
    maximum_internal_closure = float(
        strata[[f"{metric}_closure_error" for metric in METRICS]].abs().to_numpy().max()
    )
    checks = {
        "expected_annual_rows": len(annual) == 32,
        "expected_event_rows": len(event) == 29,
        "expected_stratum_rows": len(strata) == 29,
        "event_summary_matches_frozen_reference": event_difference <= TOLERANCE,
        "stratum_summary_matches_authoritative_reference": stratum_difference <= TOLERANCE,
        "stratum_additivity_closes": maximum_internal_closure <= TOLERANCE,
        "source_cell_counts_match_frozen_opening": len(annual_cells) == 406_976
        and len(contributions) == 1_475_288,
    }
    receipt = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "run_type": "clean_derived_result_replay_without_network_recomputation",
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            str(ANNUAL_SOURCE.relative_to(ROOT)): sha256(ANNUAL_SOURCE),
            str(EVENT_SOURCE.relative_to(ROOT)): sha256(EVENT_SOURCE),
        },
        "maximum_absolute_event_reference_difference": event_difference,
        "maximum_absolute_stratum_reference_difference": stratum_difference,
        "maximum_absolute_stratum_closure_error": maximum_internal_closure,
        "checks": checks,
        "outputs": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (annual_path, event_path, strata_path)
        },
    }
    receipt_path = output_dir / "DERIVED_REPLAY_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
