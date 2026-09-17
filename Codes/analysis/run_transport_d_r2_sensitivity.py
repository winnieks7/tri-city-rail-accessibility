#!/usr/bin/env python3
"""Run the predeclared R2 conservative-impedance D sensitivity once."""

from __future__ import annotations

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
    add_station_indices,
    build_summaries,
    evaluate_state,
    prepare_origins,
)
from Codes.analysis.transport_d_network_assembler import DNetworkAssembler  # noqa: E402
from Codes.analysis.transport_event_state import FrozenEventStateBuilder  # noqa: E402
from Codes.analysis.transport_shapley import closure_diagnostics, exact_shapley  # noqa: E402


CONFIG = ROOT / "Codes/config/transport_d_r2_sensitivity_run.json"
PREOPEN = ROOT / "Results/pilots/transport_d_accessibility_preopen_manifest.json"
R0_OPENING = ROOT / "Results/transport_d_accessibility_opening.json"
MARKER = ROOT / "Results/transport_d_r2_sensitivity.json"
CELL_OUT = ROOT / "Data/processed/transport/d_project_attribution_cell_r2.parquet"
CITY_OUT = ROOT / "Results/tables/transport_d_project_city_summary_r2.parquet"
SUMMARY_OUT = ROOT / "Results/tables/transport_d_project_summary_r2.csv"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def validate() -> tuple[dict, dict]:
    if MARKER.exists():
        raise RuntimeError("R2 sensitivity marker exists; rerun prohibited")
    r0 = json.loads(R0_OPENING.read_text(encoding="utf-8"))
    if r0["status"] != "complete" or not r0["all_years_close"]:
        raise RuntimeError("R0 opening is not complete and closed")
    preopen = json.loads(PREOPEN.read_text(encoding="utf-8"))
    for relative_path, expected in preopen["frozen_hashes"].items():
        if sha256(ROOT / relative_path) != expected:
            raise RuntimeError(f"pre-open frozen artifact changed: {relative_path}")
    return r0, preopen


def main() -> int:
    r0, preopen = validate()
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    base_cfg = json.loads((ROOT / cfg["base_run"]).read_text(encoding="utf-8"))
    run_cfg = {**base_cfg, **cfg}
    started = datetime.now(timezone.utc).isoformat()
    MARKER.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "started_at_utc": started,
                "variant": "r2",
                "frozen_R2_assembler_audited_preopen": True,
                "rerun_prohibited": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    state_builder = FrozenEventStateBuilder()
    assembler = DNetworkAssembler()
    origins = prepare_origins(base_cfg)
    origin_index = dict(zip(origins["grid_id"], origins.index))
    contract = json.loads(
        (ROOT / base_cfg["contract"]).read_text(encoding="utf-8")
    )
    city_order = {
        city: index for index, city in enumerate(contract["scope"]["inferential_cities"])
    }
    origin_city_codes = origins["city"].map(city_order).to_numpy(dtype=np.int64)
    destination = pd.read_parquet(DESTINATION_SNAPS)
    destination = destination.loc[
        destination["routing_relevant"] & destination["is_snapped"],
        ["pixel_id", "city", "population"],
    ].sort_values("pixel_id").reset_index(drop=True)
    destination_index = dict(zip(destination["pixel_id"], destination.index))
    destination_population = destination["population"].to_numpy(dtype=np.float64)
    destination_city_codes = destination["city"].map(city_order).to_numpy(dtype=np.int64)
    origin_walk = add_station_indices(pd.read_parquet(ORIGIN_WALK), assembler)
    destination_walk = add_station_indices(pd.read_parquet(DESTINATION_WALK), assembler)
    contribution_frames = []
    closure_by_year = []
    state_count = 0
    metrics = ["total_opportunity", "cross_city_opportunity", "coverage"]
    for year in range(2018, 2025):
        packages = state_builder.packages_by_year[year]
        event_ids = [item["event_id"] for item in packages]
        values = np.empty(
            (1 << len(packages), len(origins), len(metrics)), dtype=np.float64
        )
        for mask in range(1 << len(packages)):
            selected = {
                event_ids[index]
                for index in range(len(packages))
                if mask & (1 << index)
            }
            state = state_builder.build(year, selected)
            values[mask], _ = evaluate_state(
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
            state_count += 1
        phi = exact_shapley(values, len(packages))
        valid = origins["analysis_status"].ne("missing_walk_snap").to_numpy()
        closure = closure_diagnostics(
            phi[:, valid, :],
            values[0, valid, :],
            values[-1, valid, :],
            cfg["closure_absolute_tolerance"],
            cfg["closure_relative_tolerance"],
        )
        closure_by_year.append({"year": year, **closure})
        if not closure["passed"]:
            raise RuntimeError(f"R2 Shapley closure failed for {year}")
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
            frame["baseline_coverage"] = values[0, :, 2]
            frame["total_opportunity_contribution"] = phi[package_index, :, 0]
            frame["cross_city_opportunity_contribution"] = phi[package_index, :, 1]
            frame["coverage_contribution"] = phi[package_index, :, 2]
            contribution_frames.append(frame)
    output = pd.concat(contribution_frames, ignore_index=True)
    city, summary = build_summaries(output)
    CELL_OUT.parent.mkdir(parents=True, exist_ok=True)
    CITY_OUT.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(CELL_OUT, index=False)
    city.to_parquet(CITY_OUT, index=False)
    summary.to_csv(SUMMARY_OUT, index=False)
    result = {
        "status": "complete",
        "variant": "r2",
        "started_at_utc": started,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "rerun_prohibited": True,
        "method_rules_changed_after_R0": False,
        "preopen_frozen_hashes_verified": len(preopen["frozen_hashes"]),
        "R0_opening_sha256": sha256(R0_OPENING),
        "config_sha256": sha256(CONFIG),
        "coalition_states": state_count,
        "closure": closure_by_year,
        "all_years_close": all(item["passed"] for item in closure_by_year),
        "outputs": {
            str(CELL_OUT.relative_to(ROOT)): {"rows": len(output), "sha256": sha256(CELL_OUT)},
            str(CITY_OUT.relative_to(ROOT)): {"rows": len(city), "sha256": sha256(CITY_OUT)},
            str(SUMMARY_OUT.relative_to(ROOT)): {"rows": len(summary), "sha256": sha256(SUMMARY_OUT)},
        },
    }
    MARKER.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
