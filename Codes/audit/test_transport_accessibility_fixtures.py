#!/usr/bin/env python3
"""Synthetic fixtures for the rail-required accessibility numerical core."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Codes.analysis.transport_accessibility import (  # noqa: E402
    origin_accessibility_metrics,
    rail_required_distance_matrix,
)


MODULE = ROOT / "Codes/analysis/transport_accessibility.py"
OUTPUT = ROOT / "Results/pilots/transport_accessibility_synthetic_fixtures.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    # Stations 0-1 are line A, 2-3 line B. A transfer 1->2 costs 7 minutes.
    required = rail_required_distance_matrix(
        4,
        track_from=np.array([0, 1, 2, 3]),
        track_to=np.array([1, 0, 3, 2]),
        track_minutes=np.array([10.0, 10.0, 20.0, 20.0]),
        transfer_from=np.array([1, 2]),
        transfer_to=np.array([2, 1]),
        transfer_minutes=np.array([7.0, 5.0]),
    )
    population = np.array([100.0, 200.0, 300.0])
    city = np.array([0, 1, 1])
    total, cross, coverage = origin_accessibility_metrics(
        required,
        boarding_station_indices=np.array([0]),
        boarding_walk_plus_wait_minutes=np.array([5.0]),
        egress_station_indices=np.array([0, 1, 3]),
        egress_destination_indices=np.array([0, 1, 2]),
        egress_walk_minutes=np.array([1.0, 2.0, 3.0]),
        destination_population=population,
        destination_city_codes=city,
        origin_city_code=0,
    )
    expected_times = np.array([np.inf, 17.0, 45.0])
    expected_effective = population * np.exp(
        -np.log(2.0) * expected_times / 30.0
    )
    expected_total = float(np.nansum(expected_effective))
    expected_cross = float(np.nansum(expected_effective[1:]))

    transfer_only = rail_required_distance_matrix(
        2,
        track_from=np.array([], dtype=int),
        track_to=np.array([], dtype=int),
        track_minutes=np.array([], dtype=float),
        transfer_from=np.array([0]),
        transfer_to=np.array([1]),
        transfer_minutes=np.array([0.0]),
    )
    no_board_total, no_board_cross, no_board_coverage = origin_accessibility_metrics(
        required,
        np.array([], dtype=int),
        np.array([], dtype=float),
        np.array([1]),
        np.array([0]),
        np.array([0.0]),
        np.array([100.0]),
        np.array([1]),
        0,
    )
    checks = {
        "direct_track_time_is_exact": required[0, 1] == 10.0,
        "track_transfer_track_time_is_exact": required[0, 3] == 37.0,
        "same_occurrence_loop_is_prohibited": np.isinf(np.diag(required)).all(),
        "transfer_only_path_is_not_rail_access": np.isinf(transfer_only).all(),
        "coverage_requires_an_active_boarding_pair": coverage == 1.0
        and no_board_coverage == 0.0,
        "total_accessibility_matches_manual_decay": np.isclose(
            total, expected_total, atol=1e-10, rtol=1e-12
        ),
        "cross_city_accessibility_matches_manual_decay": np.isclose(
            cross, expected_cross, atol=1e-10, rtol=1e-12
        ),
        "no_boarding_returns_zero_opportunity": no_board_total == 0.0
        and no_board_cross == 0.0,
        "maximum_time_is_enforced": origin_accessibility_metrics(
            required,
            np.array([0]),
            np.array([100.0]),
            np.array([1]),
            np.array([0]),
            np.array([11.0]),
            np.array([100.0]),
            np.array([1]),
            0,
            maximum_time_min=120.0,
        )[0]
        == 0.0,
    }
    checks = {name: bool(value) for name, value in checks.items()}
    result = {
        "audit": "transport_accessibility_synthetic_fixtures",
        "passed": all(checks.values()),
        "n_checks": len(checks),
        "n_passed": int(sum(checks.values())),
        "accessibility_outcome_read": False,
        "module_sha256": sha256(MODULE),
        "manual_fixture": {
            "total": total,
            "expected_total": expected_total,
            "cross_city": cross,
            "expected_cross_city": expected_cross,
        },
        "checks": checks,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
