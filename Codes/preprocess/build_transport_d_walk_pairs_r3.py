#!/usr/bin/env python3
"""Build deterministic D R3 walk pairs using qualifying second-nearest nodes."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Codes.preprocess.build_transport_d_walk_pairs import truncated_distances  # noqa: E402


CONFIG = ROOT / "Codes/config/transport_d_r3_sensitivity_run.json"
GRAPH_CONFIG = ROOT / "Codes/config/transport_pedestrian_graph_20260826_r2.json"
GATE_CONFIG = ROOT / "Codes/config/transport_pedestrian_snap_gate_20260826_r1.json"
NODES = ROOT / "Data/interim/transport/pedestrian_nodes.parquet"
EDGES = ROOT / "Data/interim/transport/pedestrian_edges.parquet"
ORIGIN_SNAPS = ROOT / "Data/interim/transport/pedestrian_origin_snaps_500m.parquet"
DESTINATION_SNAPS = ROOT / "Data/interim/transport/pedestrian_destination_snaps_worldpop2023.parquet"
STATION_SNAPS = ROOT / "Data/interim/transport/pedestrian_station_snaps.parquet"
ANNUAL_STOPS = ROOT / "Data/interim/transport/d_annual_active_passenger_stops.parquet"
ORIGIN_OUT = ROOT / "Data/interim/transport/d_pedestrian_origin_station_walk_r3.parquet"
DESTINATION_OUT = ROOT / "Data/interim/transport/d_pedestrian_station_destination_walk_r3.parquet"
METADATA_OUT = ROOT / "Data/metadata/transport/transport_d_walk_pairs_r3.json"
AUDIT_OUT = ROOT / "Results/pilots/transport_d_walk_pair_r3_audit.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_variant(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    replacement = output["second_node_qualified"].astype(bool)
    output["selected_node_index"] = np.where(
        replacement, output["second_node_index"], output["nearest_node_index"]
    ).astype(np.int64)
    output["selected_node_id"] = np.where(
        replacement, output["second_node_id"], output["nearest_node_id"]
    )
    output["selected_distance_m"] = np.where(
        replacement, output["second_distance_m"], output["nearest_distance_m"]
    ).astype(float)
    output["r3_replaced"] = replacement
    return output


def target_lookup(frame: pd.DataFrame) -> dict[int, list[int]]:
    lookup: dict[int, list[int]] = defaultdict(list)
    for row_index, node_index in enumerate(frame["selected_node_index"]):
        lookup[int(node_index)].append(row_index)
    return lookup


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    graph_cfg = json.loads(GRAPH_CONFIG.read_text(encoding="utf-8"))
    gate = json.loads(GATE_CONFIG.read_text(encoding="utf-8"))
    nodes = pd.read_parquet(NODES, columns=["node_index", "is_largest_component"])
    edges = pd.read_parquet(
        EDGES,
        columns=["from_index", "to_index", "length_m", "forward_allowed", "backward_allowed"],
    )
    routing = nodes["is_largest_component"].to_numpy()
    edges = edges.loc[
        routing[edges["from_index"].to_numpy()]
        & routing[edges["to_index"].to_numpy()]
    ]
    forward = edges.loc[edges["forward_allowed"]]
    backward = edges.loc[edges["backward_allowed"]]
    rows = np.concatenate([forward["from_index"], backward["to_index"]])
    columns = np.concatenate([forward["to_index"], backward["from_index"]])
    weights = np.concatenate([forward["length_m"], backward["length_m"]])
    graph = csr_matrix((weights, (rows, columns)), shape=(len(nodes), len(nodes)))
    graph.sum_duplicates()
    reverse_graph = graph.transpose().tocsr()

    origin_scope = set(gate["development_stage"]["origin_cities"])
    origins = pd.read_parquet(ORIGIN_SNAPS)
    origins = origins.loc[
        origins["city"].isin(origin_scope)
        & origins["routing_relevant"]
        & origins["is_snapped"]
    ].reset_index(drop=True)
    origins = select_variant(origins)
    destinations = pd.read_parquet(DESTINATION_SNAPS)
    destinations = destinations.loc[
        destinations["routing_relevant"] & destinations["is_snapped"]
    ].reset_index(drop=True)
    destinations = select_variant(destinations)
    station_snaps = select_variant(pd.read_parquet(STATION_SNAPS))
    annual = pd.read_parquet(ANNUAL_STOPS)
    union_keys = annual.loc[
        annual["passenger_service_active"],
        ["sequence_id", "route_identity", "stop_order"],
    ].drop_duplicates()
    stations = union_keys.merge(
        station_snaps,
        on=["sequence_id", "route_identity", "stop_order"],
        how="left",
        validate="one_to_one",
    )
    stations = stations.loc[stations["is_snapped"]].reset_index(drop=True)

    origin_targets = target_lookup(origins)
    destination_targets = target_lookup(destinations)
    stations_by_node: dict[int, list[int]] = defaultdict(list)
    for row_index, node_index in enumerate(stations["selected_node_index"]):
        stations_by_node[int(node_index)].append(row_index)

    maximum_m = float(gate["routing_relevance"]["necessary_euclidean_distance_m"])
    speed_m_min = float(graph_cfg["network"]["walk_speed_kmh"] * 1000 / 60)
    origin_rows: list[dict] = []
    destination_rows: list[dict] = []
    for station_node, station_indices in sorted(stations_by_node.items()):
        access = truncated_distances(reverse_graph, station_node, maximum_m)
        egress = truncated_distances(graph, station_node, maximum_m)
        for node_index, graph_distance in access.items():
            for origin_index in origin_targets.get(node_index, []):
                origin = origins.iloc[origin_index]
                for station_index in station_indices:
                    station = stations.iloc[station_index]
                    total = float(origin["selected_distance_m"] + graph_distance + station["selected_distance_m"])
                    if total > maximum_m:
                        continue
                    origin_rows.append({
                        "grid_id": origin["grid_id"],
                        "origin_city": origin["city"],
                        "sequence_id": station["sequence_id"],
                        "route_identity": station["route_identity"],
                        "stop_order": int(station["stop_order"]),
                        "station_name": station["station_name"],
                        "origin_connector_m": float(origin["selected_distance_m"]),
                        "graph_distance_m": float(graph_distance),
                        "station_connector_m": float(station["selected_distance_m"]),
                        "walk_distance_m": total,
                        "walk_min": total / speed_m_min,
                        "origin_snap_replaced": bool(origin["r3_replaced"]),
                        "station_snap_replaced": bool(station["r3_replaced"]),
                    })
        for node_index, graph_distance in egress.items():
            for destination_index in destination_targets.get(node_index, []):
                destination = destinations.iloc[destination_index]
                for station_index in station_indices:
                    station = stations.iloc[station_index]
                    total = float(station["selected_distance_m"] + graph_distance + destination["selected_distance_m"])
                    if total > maximum_m:
                        continue
                    destination_rows.append({
                        "sequence_id": station["sequence_id"],
                        "route_identity": station["route_identity"],
                        "stop_order": int(station["stop_order"]),
                        "station_name": station["station_name"],
                        "pixel_id": destination["pixel_id"],
                        "destination_city": destination["city"],
                        "population": float(destination["population"]),
                        "station_connector_m": float(station["selected_distance_m"]),
                        "graph_distance_m": float(graph_distance),
                        "destination_connector_m": float(destination["selected_distance_m"]),
                        "walk_distance_m": total,
                        "walk_min": total / speed_m_min,
                        "station_snap_replaced": bool(station["r3_replaced"]),
                        "destination_snap_replaced": bool(destination["r3_replaced"]),
                    })

    origin_pairs = pd.DataFrame(origin_rows).drop_duplicates(
        ["grid_id", "sequence_id", "route_identity", "stop_order"]
    ).sort_values(["grid_id", "sequence_id", "stop_order"]).reset_index(drop=True)
    destination_pairs = pd.DataFrame(destination_rows).drop_duplicates(
        ["sequence_id", "route_identity", "stop_order", "pixel_id"]
    ).sort_values(["pixel_id", "sequence_id", "stop_order"]).reset_index(drop=True)
    ORIGIN_OUT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_OUT.parent.mkdir(parents=True, exist_ok=True)
    origin_pairs.to_parquet(ORIGIN_OUT, index=False)
    destination_pairs.to_parquet(DESTINATION_OUT, index=False)
    metadata = {
        "version": "2026-08-26-d-walk-pairs-r3-r1",
        "post_outcome_diagnostic": True,
        "predeclared_rule": True,
        "config_sha256": sha256(CONFIG),
        "inputs": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in [GRAPH_CONFIG, GATE_CONFIG, NODES, EDGES, ORIGIN_SNAPS, DESTINATION_SNAPS, STATION_SNAPS, ANNUAL_STOPS]
        },
        "replacement_counts": {
            "origins": int(origins["r3_replaced"].sum()),
            "destinations": int(destinations["r3_replaced"].sum()),
            "station_occurrences": int(stations["r3_replaced"].sum()),
        },
        "outputs": {
            str(ORIGIN_OUT.relative_to(ROOT)): {"rows": len(origin_pairs), "sha256": sha256(ORIGIN_OUT)},
            str(DESTINATION_OUT.relative_to(ROOT)): {"rows": len(destination_pairs), "sha256": sha256(DESTINATION_OUT)},
        },
    }
    METADATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    METADATA_OUT.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checks = {
        "outputs_nonempty": len(origin_pairs) > 0 and len(destination_pairs) > 0,
        "origin_keys_unique": not origin_pairs.duplicated(["grid_id", "sequence_id", "route_identity", "stop_order"]).any(),
        "destination_keys_unique": not destination_pairs.duplicated(["sequence_id", "route_identity", "stop_order", "pixel_id"]).any(),
        "walk_distances_within_limit": bool(origin_pairs["walk_distance_m"].between(0, maximum_m).all() and destination_pairs["walk_distance_m"].between(0, maximum_m).all()),
        "origin_distance_closes": bool(np.allclose(origin_pairs["walk_distance_m"], origin_pairs["origin_connector_m"] + origin_pairs["graph_distance_m"] + origin_pairs["station_connector_m"], atol=1e-8, rtol=0)),
        "destination_distance_closes": bool(np.allclose(destination_pairs["walk_distance_m"], destination_pairs["station_connector_m"] + destination_pairs["graph_distance_m"] + destination_pairs["destination_connector_m"], atol=1e-8, rtol=0)),
        "replacement_rule_changes_entities": all(value > 0 for value in metadata["replacement_counts"].values()),
        "output_hashes_match_metadata": all(sha256(ROOT / path) == item["sha256"] for path, item in metadata["outputs"].items()),
    }
    audit = {
        "audit": "transport_d_walk_pairs_r3",
        "variant": cfg["variant"],
        "counts": {
            "origin_station_pairs": len(origin_pairs),
            "station_destination_pairs": len(destination_pairs),
            "origins_with_pairs": int(origin_pairs["grid_id"].nunique()),
            "destinations_with_pairs": int(destination_pairs["pixel_id"].nunique()),
            **metadata["replacement_counts"],
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    AUDIT_OUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"metadata": metadata, "audit": audit}, ensure_ascii=False, indent=2))
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
