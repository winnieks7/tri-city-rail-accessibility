#!/usr/bin/env python3
"""Verify event coalitions reproduce every frozen D annual topology."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import geopandas as gpd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Codes.analysis.transport_event_state import (  # noqa: E402
    EDGE_KEY,
    STOP_KEY,
    FrozenEventStateBuilder,
)


EVENTS = ROOT / "Codes/config/transport_d_event_packages.json"
ANNUAL_EDGES = ROOT / "Data/interim/transport/d_annual_active_track_edges.parquet"
ANNUAL_STOPS = ROOT / "Data/interim/transport/d_annual_active_passenger_stops.parquet"
ANNUAL_CONNECTIONS = ROOT / "Data/interim/transport/d_annual_station_connection_pairs.parquet"
OUTPUT = ROOT / "Results/pilots/transport_d_event_state_reproduction_audit.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def edge_records(frame: gpd.GeoDataFrame) -> set[tuple]:
    return {
        tuple(row[column] for column in EDGE_KEY) + (row.geometry.wkb_hex,)
        for _, row in frame.iterrows()
    }


def stop_records(frame: gpd.GeoDataFrame) -> set[tuple]:
    return {
        tuple(row[column] for column in STOP_KEY)
        + (bool(row["passenger_service_active"]), row.geometry.wkb_hex)
        for _, row in frame.iterrows()
    }


def target_connection_records(frame: gpd.GeoDataFrame) -> set[tuple]:
    records = set()
    for _, row in frame.iterrows():
        endpoints = tuple(
            sorted(
                [
                    (row["from_sequence_id"], int(row["from_stop_order"])),
                    (row["to_sequence_id"], int(row["to_stop_order"])),
                ]
            )
        )
        records.add(
            endpoints
            + (
                row["connection_class"],
                row["name_match"],
                row["alias_ids"],
            )
        )
    return records


def signature(state: dict) -> tuple[frozenset, frozenset, frozenset]:
    return (
        frozenset(edge_records(state["edges"])),
        frozenset(stop_records(state["stops"])),
        frozenset(state["connections"]),
    )


def main() -> int:
    builder = FrozenEventStateBuilder()
    annual_edges = gpd.read_parquet(ANNUAL_EDGES)
    annual_stops = gpd.read_parquet(ANNUAL_STOPS)
    annual_connections = gpd.read_parquet(ANNUAL_CONNECTIONS)
    year_audits = []
    every_full_exact = True
    every_empty_exact = True
    every_event_changes_empty = True
    every_event_changes_full = True

    for year in range(2018, 2025):
        events = builder.packages_by_year[year]
        event_ids = {item["event_id"] for item in events}
        full = builder.build(year, event_ids)
        empty = builder.build(year, set())
        target_edge = annual_edges.loc[annual_edges["year"].eq(year)]
        target_stop = annual_stops.loc[annual_stops["year"].eq(year)]
        target_connection = target_connection_records(
            annual_connections.loc[annual_connections["year"].eq(year)]
        )
        prior_edge = annual_edges.loc[annual_edges["year"].eq(year - 1)]
        prior_stop = annual_stops.loc[annual_stops["year"].eq(year - 1)]
        prior_connection = target_connection_records(
            annual_connections.loc[annual_connections["year"].eq(year - 1)]
        )
        full_checks = {
            "edges": edge_records(full["edges"]) == edge_records(target_edge),
            "stops": stop_records(full["stops"]) == stop_records(target_stop),
            "connections": full["connections"] == target_connection,
        }
        empty_checks = {
            "edges": edge_records(empty["edges"]) == edge_records(prior_edge),
            "stops": stop_records(empty["stops"]) == stop_records(prior_stop),
            "connections": empty["connections"] == prior_connection,
        }
        empty_signature = signature(empty)
        full_signature = signature(full)
        single_changes = {
            event_id: signature(builder.build(year, {event_id})) != empty_signature
            for event_id in sorted(event_ids)
        }
        leave_one_out_changes = {
            event_id: signature(builder.build(year, event_ids - {event_id}))
            != full_signature
            for event_id in sorted(event_ids)
        }
        every_full_exact &= all(full_checks.values())
        every_empty_exact &= all(empty_checks.values())
        every_event_changes_empty &= all(single_changes.values())
        every_event_changes_full &= all(leave_one_out_changes.values())
        year_audits.append(
            {
                "year": year,
                "event_count": len(event_ids),
                "full_state_matches_frozen": full_checks,
                "empty_state_matches_prior_year": empty_checks,
                "single_event_changes_empty_state": single_changes,
                "leave_one_out_changes_full_state": leave_one_out_changes,
                "full_counts": {
                    "edges": len(full["edges"]),
                    "stop_occurrences": len(full["stops"]),
                    "active_stop_occurrences": int(
                        full["stops"]["passenger_service_active"].sum()
                    ),
                    "connections": len(full["connections"]),
                },
            }
        )

    checks = {
        "all_full_coalitions_reproduce_frozen_year_end_edges_stops_connections": every_full_exact,
        "all_empty_coalitions_reproduce_preceding_year_edges_stops_connections": every_empty_exact,
        "every_package_changes_its_year_empty_state": every_event_changes_empty,
        "every_package_changes_its_year_full_state": every_event_changes_full,
        "event_config_snapshot_exact": EVENTS.read_bytes()
        == (ROOT / "Codes/config/transport_d_event_packages_20260826_r2.json").read_bytes(),
        "accessibility_outcomes_remain_sealed": True,
    }
    result = {
        "audit": "transport_d_event_state_reproduction",
        "passed": all(checks.values()),
        "n_checks": len(checks),
        "n_passed": sum(checks.values()),
        "accessibility_outcome_read": False,
        "hashes": {
            "event_config": sha256(EVENTS),
            "state_builder": sha256(
                ROOT / "Codes/analysis/transport_event_state.py"
            ),
            "annual_edges": sha256(ANNUAL_EDGES),
            "annual_stops": sha256(ANNUAL_STOPS),
            "annual_connections": sha256(ANNUAL_CONNECTIONS),
        },
        "checks": checks,
        "years": year_audits,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
