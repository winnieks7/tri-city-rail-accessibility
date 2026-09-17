#!/usr/bin/env python3
"""Replay the frozen D attribution into a new, non-destructive output directory.

This entry point deliberately does not call the original one-time outcome-opening
guard.  It reads the same frozen inputs, refuses to overwrite archived results,
and writes every replay artifact below an explicit new directory.  It is supplied
for independent replication and must not be used to relabel a later replay as the
original confirmatory opening.
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

from Codes.analysis.run_transport_d_project_attribution import (  # noqa: E402
    DESTINATION_SNAPS,
    DESTINATION_WALK,
    ORIGIN_WALK,
    RUN_CONFIG,
    add_station_indices,
    build_summaries,
    evaluate_state,
    prepare_origins,
)
from Codes.analysis.transport_d_network_assembler import DNetworkAssembler  # noqa: E402
from Codes.analysis.transport_event_state import FrozenEventStateBuilder  # noqa: E402
from Codes.analysis.transport_shapley import closure_diagnostics, exact_shapley  # noqa: E402


ARCHIVED_OUTPUTS = {
    (ROOT / "Data/processed/transport/d_annual_accessibility_cell.parquet").resolve(),
    (ROOT / "Data/processed/transport/d_project_attribution_cell.parquet").resolve(),
    (ROOT / "Results/tables/transport_d_project_city_summary.parquet").resolve(),
    (ROOT / "Results/tables/transport_d_project_summary.csv").resolve(),
    (ROOT / "Results/transport_d_accessibility_opening.json").resolve(),
}
METRICS = ["total_opportunity", "cross_city_opportunity", "coverage"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New empty directory for replay artifacts; archived paths are refused.",
    )
    return parser.parse_args()


def validate_output_directory(output_dir: Path) -> Path:
    target = output_dir.expanduser().resolve()
    if target in ARCHIVED_OUTPUTS or any(path.is_relative_to(target) for path in ARCHIVED_OUTPUTS):
        raise RuntimeError("output directory would contain an archived frozen result")
    if target == ROOT.resolve():
        raise RuntimeError("project root is not a valid replay output directory")
    if target.exists() and any(target.iterdir()):
        raise RuntimeError("replay output directory must be absent or empty")
    target.mkdir(parents=True, exist_ok=True)
    return target


def equal_city_coalition_record(
    year: int,
    mask: int,
    event_ids: list[str],
    values: np.ndarray,
    origins: pd.DataFrame,
) -> dict:
    valid = origins["analysis_status"].ne("missing_walk_snap").to_numpy()
    weights = origins["population_weight"].to_numpy(dtype=np.float64)
    record: dict[str, object] = {
        "year": year,
        "mask": mask,
        "included_event_ids": json.dumps(
            [event_ids[index] for index in range(len(event_ids)) if mask & (1 << index)]
        ),
    }
    for metric_index, metric in enumerate(METRICS):
        city_values = []
        for city in sorted(origins["city"].unique()):
            selected = valid & origins["city"].eq(city).to_numpy()
            city_values.append(float(np.average(values[selected, metric_index], weights=weights[selected])))
        record[f"equal_city_population_weighted_{metric}"] = float(np.mean(city_values))
    return record


def main() -> int:
    args = parse_args()
    output_dir = validate_output_directory(args.output_dir)
    run_cfg = json.loads(RUN_CONFIG.read_text(encoding="utf-8"))
    started = datetime.now(timezone.utc).isoformat()

    state_builder = FrozenEventStateBuilder()
    assembler = DNetworkAssembler()
    origins = prepare_origins(run_cfg)
    origin_index = dict(zip(origins["grid_id"], origins.index))
    city_order = {
        city: index
        for index, city in enumerate(
            json.loads((ROOT / run_cfg["contract"]).read_text(encoding="utf-8"))["scope"][
                "inferential_cities"
            ]
        )
    }
    origin_city_codes = origins["city"].map(city_order).to_numpy(dtype=np.int64)

    destination_snap = pd.read_parquet(DESTINATION_SNAPS)
    destination = destination_snap.loc[
        destination_snap["routing_relevant"] & destination_snap["is_snapped"],
        ["pixel_id", "city", "population"],
    ].sort_values("pixel_id").reset_index(drop=True)
    destination_index = dict(zip(destination["pixel_id"], destination.index))
    destination_population = destination["population"].to_numpy(dtype=np.float64)
    destination_city_codes = destination["city"].map(city_order).to_numpy(dtype=np.int64)
    origin_walk = add_station_indices(pd.read_parquet(ORIGIN_WALK), assembler)
    destination_walk = add_station_indices(pd.read_parquet(DESTINATION_WALK), assembler)

    annual_frames: list[pd.DataFrame] = []
    contribution_frames: list[pd.DataFrame] = []
    coalition_aggregate_rows: list[dict] = []
    closure_by_year: list[dict] = []
    state_diagnostics: list[dict] = []
    baseline_written = False

    for year in range(2018, 2025):
        packages = state_builder.packages_by_year[year]
        event_ids = [item["event_id"] for item in packages]
        coalition_values = np.empty(
            (1 << len(packages), len(origins), len(METRICS)), dtype=np.float64
        )
        for mask in range(1 << len(packages)):
            selected = {
                event_ids[index]
                for index in range(len(packages))
                if mask & (1 << index)
            }
            values, diagnostics = evaluate_state(
                year,
                state_builder.build(year, selected),
                origins,
                origin_walk,
                destination_walk,
                destination_population,
                destination_city_codes,
                destination_index,
                origin_index,
                origin_city_codes,
                assembler,
                run_cfg,
            )
            coalition_values[mask] = values
            state_diagnostics.append({"year": year, "mask": mask, **diagnostics})
            coalition_aggregate_rows.append(
                equal_city_coalition_record(year, mask, event_ids, values, origins)
            )

        contributions = exact_shapley(coalition_values, len(packages))
        valid = origins["analysis_status"].ne("missing_walk_snap").to_numpy()
        closure = closure_diagnostics(
            contributions[:, valid, :],
            coalition_values[0, valid, :],
            coalition_values[-1, valid, :],
            run_cfg["closure_absolute_tolerance"],
            run_cfg["closure_relative_tolerance"],
        )
        closure_by_year.append({"year": year, **closure})
        if not closure["passed"]:
            raise RuntimeError(f"Shapley closure failed for replay year {year}")

        base_columns = [
            "grid_id",
            "city",
            "split_group",
            "population_weight",
            "area_weight_m2",
            "analysis_status",
            "block_10km",
        ]
        if not baseline_written:
            baseline = origins[base_columns].copy()
            baseline["year"] = 2017
            for index, metric in enumerate(METRICS):
                baseline[metric] = coalition_values[0, :, index]
            annual_frames.append(baseline)
            baseline_written = True
        annual = origins[base_columns].copy()
        annual["year"] = year
        for index, metric in enumerate(METRICS):
            annual[metric] = coalition_values[-1, :, index]
        annual_frames.append(annual)

        for package_index, package in enumerate(packages):
            frame = origins[base_columns].copy()
            frame["year"] = year
            frame["event_id"] = package["event_id"]
            frame["event_label"] = package["label"]
            frame["baseline_coverage"] = coalition_values[0, :, 2]
            for metric_index, metric in enumerate(METRICS):
                frame[f"{metric}_contribution"] = contributions[
                    package_index, :, metric_index
                ]
            contribution_frames.append(frame)

    annual_output = pd.concat(annual_frames, ignore_index=True)
    contribution_output = pd.concat(contribution_frames, ignore_index=True)
    city_summary, project_summary = build_summaries(contribution_output)
    outputs = {
        "d_annual_accessibility_cell.parquet": annual_output,
        "d_project_attribution_cell.parquet": contribution_output,
        "transport_d_project_city_summary.parquet": city_summary,
    }
    for filename, frame in outputs.items():
        frame.to_parquet(output_dir / filename, index=False)
    project_summary.to_csv(output_dir / "transport_d_project_summary.csv", index=False)
    pd.DataFrame(coalition_aggregate_rows).to_parquet(
        output_dir / "transport_d_coalition_equal_city_outcomes.parquet", index=False
    )
    (output_dir / "transport_d_state_diagnostics.json").write_text(
        json.dumps(state_diagnostics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    output_paths = sorted(path for path in output_dir.iterdir() if path.is_file())
    receipt = {
        "status": "complete",
        "run_type": "independent_nonconfirmatory_replay",
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "original_one_time_opening_untouched": True,
        "archived_results_overwritten": False,
        "run_config_sha256": sha256(RUN_CONFIG),
        "closure": closure_by_year,
        "all_years_close": all(item["passed"] for item in closure_by_year),
        "counts": {
            "origins": len(origins),
            "destinations": len(destination),
            "coalition_states": len(state_diagnostics),
            "coalition_aggregate_rows": len(coalition_aggregate_rows),
        },
        "outputs": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in output_paths
        },
    }
    receipt_path = output_dir / "REPLAY_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
