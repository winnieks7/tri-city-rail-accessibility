#!/usr/bin/env python3
"""One-time opening of D rail-project accessibility attribution outcomes."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Codes.analysis.transport_accessibility import (  # noqa: E402
    origin_accessibility_metrics,
    rail_required_distance_matrix,
)
from Codes.analysis.transport_d_network_assembler import (  # noqa: E402
    DNetworkAssembler,
)
from Codes.analysis.transport_event_state import FrozenEventStateBuilder  # noqa: E402
from Codes.analysis.transport_shapley import (  # noqa: E402
    closure_diagnostics,
    exact_shapley,
)


RUN_CONFIG = ROOT / "Codes/config/transport_d_accessibility_run.json"
PREOPEN = ROOT / "Results/pilots/transport_d_accessibility_preopen_manifest.json"
OPENING = ROOT / "Results/transport_d_accessibility_opening.json"
ORIGIN_WEIGHT = ROOT / "Data/processed/transport/worldpop_2023_origin_weights_500m.parquet"
ORIGIN_SNAPS = ROOT / "Data/interim/transport/pedestrian_origin_snaps_500m.parquet"
DESTINATION_SNAPS = ROOT / "Data/interim/transport/pedestrian_destination_snaps_worldpop2023.parquet"
GRID = ROOT / "Data/processed/transport/transport_grid_500m.parquet"
ORIGIN_WALK = ROOT / "Data/interim/transport/d_pedestrian_origin_station_walk.parquet"
DESTINATION_WALK = ROOT / "Data/interim/transport/d_pedestrian_station_destination_walk.parquet"
ANNUAL_OUT = ROOT / "Data/processed/transport/d_annual_accessibility_cell.parquet"
CONTRIBUTION_OUT = ROOT / "Data/processed/transport/d_project_attribution_cell.parquet"
CITY_SUMMARY_OUT = ROOT / "Results/tables/transport_d_project_city_summary.parquet"
PROJECT_SUMMARY_OUT = ROOT / "Results/tables/transport_d_project_summary.csv"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def validate_preopen() -> dict:
    if OPENING.exists():
        raise RuntimeError(
            "D opening marker already exists; one-time outcome opening cannot rerun"
        )
    preopen = json.loads(PREOPEN.read_text(encoding="utf-8"))
    if not preopen["passed"] or preopen["accessibility_outcome_read"]:
        raise RuntimeError("pre-open manifest did not authorize the one-time D run")
    for relative_path, expected in preopen["frozen_hashes"].items():
        path = ROOT / relative_path
        if sha256(path) != expected:
            raise RuntimeError(f"frozen pre-open hash changed: {relative_path}")
    return preopen


def prepare_origins(cfg: dict) -> pd.DataFrame:
    weights = pd.read_parquet(ORIGIN_WEIGHT)
    weights = weights.loc[weights["city"].isin(cfg["origin_cities"])].copy()
    snaps = pd.read_parquet(ORIGIN_SNAPS)[
        ["grid_id", "routing_relevant", "is_snapped"]
    ]
    grid = gpd.read_parquet(GRID)
    grid = grid.loc[
        grid["analysis_eligible"] & grid["gba_city"].isin(cfg["origin_cities"]),
        [
            "grid_id", "aoi_overlap_fraction", "permanent_water_fraction_within_aoi",
            "block_10km",
        ],
    ]
    origins = weights.merge(snaps, on="grid_id", validate="one_to_one").merge(
        grid, on="grid_id", validate="one_to_one"
    )
    origins["analysis_status"] = np.select(
        [
            origins["routing_relevant"] & ~origins["is_snapped"],
            ~origins["routing_relevant"],
        ],
        ["missing_walk_snap", "structural_zero"],
        default="routable",
    )
    origins["area_weight_m2"] = (
        250000.0
        * origins["aoi_overlap_fraction"]
        * (1.0 - origins["permanent_water_fraction_within_aoi"])
    )
    return origins.sort_values("grid_id").reset_index(drop=True)


def add_station_indices(frame: pd.DataFrame, assembler: DNetworkAssembler) -> pd.DataFrame:
    output = frame.copy()
    output["station_index"] = [
        assembler.station_lookup[
            (row.sequence_id, row.route_identity, int(row.stop_order))
        ]
        for row in output.itertuples(index=False)
    ]
    return output


def evaluate_state(
    year: int,
    state: dict,
    origins: pd.DataFrame,
    origin_walk: pd.DataFrame,
    destination_walk: pd.DataFrame,
    destination_population: np.ndarray,
    destination_city_codes: np.ndarray,
    destination_index: dict[str, int],
    origin_index: dict[str, int],
    origin_city_codes: np.ndarray,
    assembler: DNetworkAssembler,
    run_cfg: dict,
) -> tuple[np.ndarray, dict]:
    network = assembler.assemble(year, state, run_cfg["impedance_variant"])
    required = rail_required_distance_matrix(
        len(assembler.stations),
        network.track_from,
        network.track_to,
        network.track_minutes,
        network.transfer_from,
        network.transfer_to,
        network.transfer_minutes,
    )
    active = set(network.active_station_indices.tolist())
    active_origin_walk = origin_walk.loc[
        origin_walk["station_index"].isin(active)
    ].copy()
    active_destination_walk = destination_walk.loc[
        destination_walk["station_index"].isin(active)
    ].copy()
    active_destination_walk["destination_index"] = active_destination_walk[
        "pixel_id"
    ].map(destination_index)
    egress_station = active_destination_walk["station_index"].to_numpy(dtype=np.int64)
    egress_destination = active_destination_walk["destination_index"].to_numpy(
        dtype=np.int64
    )
    egress_walk = active_destination_walk["walk_min"].to_numpy(dtype=np.float64)
    values = np.zeros((len(origins), 3), dtype=np.float64)
    missing = origins["analysis_status"].eq("missing_walk_snap").to_numpy()
    values[missing] = np.nan
    evaluated = 0
    for grid_id, pairs in active_origin_walk.groupby("grid_id", sort=False):
        row_index = origin_index[grid_id]
        waits = pairs["route_identity"].map(network.boarding_wait_by_route)
        if waits.isna().any():
            raise RuntimeError(f"missing boarding wait in {year} coalition")
        total, cross, coverage = origin_accessibility_metrics(
            required,
            pairs["station_index"].to_numpy(dtype=np.int64),
            pairs["walk_min"].to_numpy(dtype=np.float64)
            + waits.to_numpy(dtype=np.float64),
            egress_station,
            egress_destination,
            egress_walk,
            destination_population,
            destination_city_codes,
            int(origin_city_codes[row_index]),
            maximum_time_min=run_cfg["maximum_time_min"],
            half_life_min=run_cfg["half_life_min"],
        )
        values[row_index] = [total, cross, coverage]
        evaluated += 1
    diagnostics = {
        **network.diagnostics,
        "origins_evaluated_with_active_walk_pair": evaluated,
        "active_origin_walk_pairs": len(active_origin_walk),
        "active_destination_walk_pairs": len(active_destination_walk),
    }
    return values, diagnostics


def build_summaries(contributions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    metric_columns = [
        "total_opportunity_contribution",
        "cross_city_opportunity_contribution",
        "coverage_contribution",
    ]
    for (event_id, year, label, city), group in contributions.groupby(
        ["event_id", "year", "event_label", "city"], sort=False
    ):
        valid = group["analysis_status"].ne("missing_walk_snap")
        selected = group.loc[valid]
        pop_denominator = float(selected["population_weight"].sum())
        area_denominator = float(selected["area_weight_m2"].sum())
        record = {
            "event_id": event_id,
            "year": int(year),
            "event_label": label,
            "geography": city,
            "population_denominator": pop_denominator,
            "area_denominator_m2": area_denominator,
            "missing_relevant_population": float(
                group.loc[~valid, "population_weight"].sum()
            ),
        }
        for metric in metric_columns:
            record[f"population_weighted_{metric}"] = float(
                (selected[metric] * selected["population_weight"]).sum()
                / pop_denominator
            )
            record[f"area_weighted_{metric}"] = float(
                (selected[metric] * selected["area_weight_m2"]).sum()
                / area_denominator
            )
        for baseline_value, suffix in ((0.0, "uncovered"), (1.0, "covered")):
            stratum = selected.loc[selected["baseline_coverage"].eq(baseline_value)]
            denominator = float(stratum["population_weight"].sum())
            record[f"{suffix}_population_denominator"] = denominator
            record[f"population_weighted_total_contribution_{suffix}"] = (
                float(
                    (
                        stratum["total_opportunity_contribution"]
                        * stratum["population_weight"]
                    ).sum()
                    / denominator
                )
                if denominator > 0
                else np.nan
            )
        rows.append(record)
    city = pd.DataFrame(rows)
    aggregate_rows = []
    value_columns = [
        column
        for column in city.columns
        if column.startswith("population_weighted_")
        or column.startswith("area_weighted_")
    ]
    for (event_id, year, label), group in city.groupby(
        ["event_id", "year", "event_label"], sort=False
    ):
        record = {
            "event_id": event_id,
            "year": int(year),
            "event_label": label,
            "geography": "D_equal_city",
            "cities": len(group),
        }
        for column in value_columns:
            record[column] = float(group[column].mean())
        aggregate_rows.append(record)
    return city, pd.DataFrame(aggregate_rows)


def main() -> int:
    preopen = validate_preopen()
    run_cfg = json.loads(RUN_CONFIG.read_text(encoding="utf-8"))
    started = datetime.now(timezone.utc).isoformat()
    OPENING.parent.mkdir(parents=True, exist_ok=True)
    OPENING.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "started_at_utc": started,
                "preopen_manifest_sha256": sha256(PREOPEN),
                "accessibility_outcome_read": True,
                "rerun_prohibited": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    state_builder = FrozenEventStateBuilder()
    assembler = DNetworkAssembler()
    origins = prepare_origins(run_cfg)
    origin_index = dict(zip(origins["grid_id"], origins.index))
    city_order = {
        city: index
        for index, city in enumerate(
            json.loads(
                (ROOT / run_cfg["contract"]).read_text(encoding="utf-8")
            )["scope"]["inferential_cities"]
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
    destination_walk = add_station_indices(
        pd.read_parquet(DESTINATION_WALK), assembler
    )
    annual_frames = []
    contribution_frames = []
    closure_by_year = []
    state_diagnostics = []
    baseline_written = False
    metrics = ["total_opportunity", "cross_city_opportunity", "coverage"]

    for year in range(2018, 2025):
        packages = state_builder.packages_by_year[year]
        event_ids = [item["event_id"] for item in packages]
        coalition_values = np.empty(
            (1 << len(packages), len(origins), len(metrics)), dtype=np.float64
        )
        for mask in range(1 << len(packages)):
            selected = {
                event_ids[index]
                for index in range(len(packages))
                if mask & (1 << index)
            }
            state = state_builder.build(year, selected)
            values, diagnostics = evaluate_state(
                year,
                state,
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
            state_diagnostics.append(
                {"year": year, "mask": mask, **diagnostics}
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
            raise RuntimeError(f"Shapley closure failed for {year}")

        if not baseline_written:
            baseline = origins[
                [
                    "grid_id", "city", "split_group", "population_weight",
                    "area_weight_m2", "analysis_status", "block_10km",
                ]
            ].copy()
            baseline["year"] = 2017
            for index, metric in enumerate(metrics):
                baseline[metric] = coalition_values[0, :, index]
            annual_frames.append(baseline)
            baseline_written = True
        annual = origins[
            [
                "grid_id", "city", "split_group", "population_weight",
                "area_weight_m2", "analysis_status", "block_10km",
            ]
        ].copy()
        annual["year"] = year
        for index, metric in enumerate(metrics):
            annual[metric] = coalition_values[-1, :, index]
        annual_frames.append(annual)

        for package_index, package in enumerate(packages):
            frame = origins[
                [
                    "grid_id", "city", "split_group", "population_weight",
                    "area_weight_m2", "analysis_status", "block_10km",
                ]
            ].copy()
            frame["year"] = year
            frame["event_id"] = package["event_id"]
            frame["event_label"] = package["label"]
            frame["baseline_coverage"] = coalition_values[0, :, 2]
            frame["total_opportunity_contribution"] = contributions[
                package_index, :, 0
            ]
            frame["cross_city_opportunity_contribution"] = contributions[
                package_index, :, 1
            ]
            frame["coverage_contribution"] = contributions[package_index, :, 2]
            contribution_frames.append(frame)

    annual_output = pd.concat(annual_frames, ignore_index=True)
    contribution_output = pd.concat(contribution_frames, ignore_index=True)
    city_summary, project_summary = build_summaries(contribution_output)
    ANNUAL_OUT.parent.mkdir(parents=True, exist_ok=True)
    CITY_SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    annual_output.to_parquet(ANNUAL_OUT, index=False)
    contribution_output.to_parquet(CONTRIBUTION_OUT, index=False)
    city_summary.to_parquet(CITY_SUMMARY_OUT, index=False)
    project_summary.to_csv(PROJECT_SUMMARY_OUT, index=False)
    completed = datetime.now(timezone.utc).isoformat()
    result = {
        "status": "complete",
        "started_at_utc": started,
        "completed_at_utc": completed,
        "accessibility_outcome_read": True,
        "rerun_prohibited": True,
        "run_config_sha256": sha256(RUN_CONFIG),
        "preopen_manifest_sha256": sha256(PREOPEN),
        "preopen_frozen_hash_count": len(preopen["frozen_hashes"]),
        "counts": {
            "origins": len(origins),
            "valid_origins": int(origins["analysis_status"].ne("missing_walk_snap").sum()),
            "destinations": len(destination),
            "annual_rows": len(annual_output),
            "project_cell_rows": len(contribution_output),
            "project_city_rows": len(city_summary),
            "project_summary_rows": len(project_summary),
            "coalition_states": len(state_diagnostics),
        },
        "closure": closure_by_year,
        "all_years_close": all(item["passed"] for item in closure_by_year),
        "outputs": {
            str(ANNUAL_OUT.relative_to(ROOT)): {
                "rows": len(annual_output), "sha256": sha256(ANNUAL_OUT)
            },
            str(CONTRIBUTION_OUT.relative_to(ROOT)): {
                "rows": len(contribution_output), "sha256": sha256(CONTRIBUTION_OUT)
            },
            str(CITY_SUMMARY_OUT.relative_to(ROOT)): {
                "rows": len(city_summary), "sha256": sha256(CITY_SUMMARY_OUT)
            },
            str(PROJECT_SUMMARY_OUT.relative_to(ROOT)): {
                "rows": len(project_summary), "sha256": sha256(PROJECT_SUMMARY_OUT)
            },
        },
        "state_diagnostics": state_diagnostics,
    }
    OPENING.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in result.items() if key != "state_diagnostics"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
