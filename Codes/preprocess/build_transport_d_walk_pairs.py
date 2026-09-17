#!/usr/bin/env python3
"""Build outcome-blind D origin/station and station/destination walk pairs."""

from __future__ import annotations

import hashlib
import heapq
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix


ROOT = Path(__file__).resolve().parents[2]
GRAPH_CONFIG = ROOT / "Codes/config/transport_pedestrian_graph_20260826_r2.json"
GATE_CONFIG = ROOT / "Codes/config/transport_pedestrian_snap_gate_20260826_r1.json"
NODES = ROOT / "Data/interim/transport/pedestrian_nodes.parquet"
EDGES = ROOT / "Data/interim/transport/pedestrian_edges.parquet"
ORIGIN_SNAPS = ROOT / "Data/interim/transport/pedestrian_origin_snaps_500m.parquet"
DESTINATION_SNAPS = ROOT / "Data/interim/transport/pedestrian_destination_snaps_worldpop2023.parquet"
STATION_SNAPS = ROOT / "Data/interim/transport/pedestrian_station_snaps.parquet"
ANNUAL_STOPS = ROOT / "Data/interim/transport/d_annual_active_passenger_stops.parquet"
ORIGIN_OUT = ROOT / "Data/interim/transport/d_pedestrian_origin_station_walk.parquet"
DESTINATION_OUT = ROOT / "Data/interim/transport/d_pedestrian_station_destination_walk.parquet"
METADATA_OUT = ROOT / "Data/metadata/transport/transport_d_walk_pairs.json"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def truncated_distances(graph: csr_matrix, source: int, limit: float) -> dict[int, float]:
    distances = {source: 0.0}
    queue = [(0.0, source)]
    indptr = graph.indptr
    indices = graph.indices
    weights = graph.data
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        if distance > limit:
            break
        for position in range(indptr[node], indptr[node + 1]):
            neighbor = int(indices[position])
            candidate = distance + float(weights[position])
            if candidate > limit or candidate >= distances.get(neighbor, np.inf):
                continue
            distances[neighbor] = candidate
            heapq.heappush(queue, (candidate, neighbor))
    return distances


def target_lookup(frame: pd.DataFrame) -> dict[int, list[int]]:
    lookup: dict[int, list[int]] = defaultdict(list)
    for row_index, node_index in enumerate(frame["nearest_node_index"]):
        lookup[int(node_index)].append(row_index)
    return lookup


def main() -> int:
    graph_cfg = json.loads(GRAPH_CONFIG.read_text(encoding="utf-8"))
    gate = json.loads(GATE_CONFIG.read_text(encoding="utf-8"))
    nodes = pd.read_parquet(
        NODES, columns=["node_index", "is_largest_component"]
    )
    edges = pd.read_parquet(
        EDGES,
        columns=[
            "from_index", "to_index", "length_m", "forward_allowed",
            "backward_allowed",
        ],
    )
    routing_mask = nodes["is_largest_component"].to_numpy()
    edge_mask = routing_mask[edges["from_index"].to_numpy()] & routing_mask[
        edges["to_index"].to_numpy()
    ]
    edges = edges.loc[edge_mask].copy()
    forward = edges.loc[edges["forward_allowed"]]
    backward = edges.loc[edges["backward_allowed"]]
    rows = np.concatenate(
        [forward["from_index"].to_numpy(), backward["to_index"].to_numpy()]
    )
    columns = np.concatenate(
        [forward["to_index"].to_numpy(), backward["from_index"].to_numpy()]
    )
    weights = np.concatenate(
        [forward["length_m"].to_numpy(), backward["length_m"].to_numpy()]
    )
    graph = csr_matrix(
        (weights, (rows, columns)), shape=(len(nodes), len(nodes))
    )
    graph.sum_duplicates()
    reverse_graph = graph.transpose().tocsr()

    origin_scope = set(gate["development_stage"]["origin_cities"])
    origins = pd.read_parquet(ORIGIN_SNAPS)
    origins = origins.loc[
        origins["city"].isin(origin_scope)
        & origins["routing_relevant"]
        & origins["is_snapped"]
    ].reset_index(drop=True)
    destinations = pd.read_parquet(DESTINATION_SNAPS)
    destinations = destinations.loc[
        destinations["routing_relevant"] & destinations["is_snapped"]
    ].reset_index(drop=True)
    station_snaps = pd.read_parquet(STATION_SNAPS)
    annual_stops = pd.read_parquet(ANNUAL_STOPS)
    union_station_keys = annual_stops.loc[
        annual_stops["passenger_service_active"],
        ["sequence_id", "route_identity", "stop_order"],
    ].drop_duplicates()
    stations = union_station_keys.merge(
        station_snaps,
        on=["sequence_id", "route_identity", "stop_order"],
        how="left",
        validate="one_to_one",
    )
    stations = stations.loc[stations["is_snapped"]].reset_index(drop=True)

    origin_targets = target_lookup(origins)
    destination_targets = target_lookup(destinations)
    stations_by_node: dict[int, list[int]] = defaultdict(list)
    for station_index, node_index in enumerate(stations["nearest_node_index"]):
        stations_by_node[int(node_index)].append(station_index)

    maximum_m = gate["routing_relevance"]["necessary_euclidean_distance_m"]
    speed_m_min = graph_cfg["network"]["walk_speed_kmh"] * 1000 / 60
    origin_rows = []
    destination_rows = []
    visited_reverse = 0
    visited_forward = 0
    for station_node, station_indices in sorted(stations_by_node.items()):
        access_distances = truncated_distances(reverse_graph, station_node, maximum_m)
        egress_distances = truncated_distances(graph, station_node, maximum_m)
        visited_reverse += len(access_distances)
        visited_forward += len(egress_distances)
        for node_index, graph_distance in access_distances.items():
            if node_index not in origin_targets:
                continue
            for origin_index in origin_targets[node_index]:
                origin = origins.iloc[origin_index]
                for station_index in station_indices:
                    station = stations.iloc[station_index]
                    total = (
                        float(origin["nearest_distance_m"])
                        + graph_distance
                        + float(station["nearest_distance_m"])
                    )
                    if total > maximum_m:
                        continue
                    origin_rows.append(
                        {
                            "grid_id": origin["grid_id"],
                            "origin_city": origin["city"],
                            "sequence_id": station["sequence_id"],
                            "route_identity": station["route_identity"],
                            "stop_order": int(station["stop_order"]),
                            "station_name": station["station_name"],
                            "origin_connector_m": float(origin["nearest_distance_m"]),
                            "graph_distance_m": graph_distance,
                            "station_connector_m": float(station["nearest_distance_m"]),
                            "walk_distance_m": total,
                            "walk_min": total / speed_m_min,
                        }
                    )
        for node_index, graph_distance in egress_distances.items():
            if node_index not in destination_targets:
                continue
            for destination_index in destination_targets[node_index]:
                destination = destinations.iloc[destination_index]
                for station_index in station_indices:
                    station = stations.iloc[station_index]
                    total = (
                        float(station["nearest_distance_m"])
                        + graph_distance
                        + float(destination["nearest_distance_m"])
                    )
                    if total > maximum_m:
                        continue
                    destination_rows.append(
                        {
                            "sequence_id": station["sequence_id"],
                            "route_identity": station["route_identity"],
                            "stop_order": int(station["stop_order"]),
                            "station_name": station["station_name"],
                            "pixel_id": destination["pixel_id"],
                            "destination_city": destination["city"],
                            "population": float(destination["population"]),
                            "station_connector_m": float(station["nearest_distance_m"]),
                            "graph_distance_m": graph_distance,
                            "destination_connector_m": float(
                                destination["nearest_distance_m"]
                            ),
                            "walk_distance_m": total,
                            "walk_min": total / speed_m_min,
                        }
                    )

    origin_pairs = pd.DataFrame(origin_rows).drop_duplicates(
        ["grid_id", "sequence_id", "route_identity", "stop_order"]
    )
    destination_pairs = pd.DataFrame(destination_rows).drop_duplicates(
        ["sequence_id", "route_identity", "stop_order", "pixel_id"]
    )
    origin_pairs = origin_pairs.sort_values(
        ["grid_id", "sequence_id", "stop_order"]
    ).reset_index(drop=True)
    destination_pairs = destination_pairs.sort_values(
        ["pixel_id", "sequence_id", "stop_order"]
    ).reset_index(drop=True)
    ORIGIN_OUT.parent.mkdir(parents=True, exist_ok=True)
    origin_pairs.to_parquet(ORIGIN_OUT, index=False)
    destination_pairs.to_parquet(DESTINATION_OUT, index=False)
    metadata = {
        "version": "2026-08-26-d-walk-pairs-r1",
        "accessibility_outcome_read": False,
        "inputs": {
            str(GRAPH_CONFIG.relative_to(ROOT)): sha256(GRAPH_CONFIG),
            str(GATE_CONFIG.relative_to(ROOT)): sha256(GATE_CONFIG),
            str(NODES.relative_to(ROOT)): sha256(NODES),
            str(EDGES.relative_to(ROOT)): sha256(EDGES),
            str(ORIGIN_SNAPS.relative_to(ROOT)): sha256(ORIGIN_SNAPS),
            str(DESTINATION_SNAPS.relative_to(ROOT)): sha256(DESTINATION_SNAPS),
            str(STATION_SNAPS.relative_to(ROOT)): sha256(STATION_SNAPS),
            str(ANNUAL_STOPS.relative_to(ROOT)): sha256(ANNUAL_STOPS),
        },
        "routing": {
            "directed_csr_arcs": int(graph.nnz),
            "unique_station_nodes": len(stations_by_node),
            "snapped_union_station_occurrences": len(stations),
            "eligible_origins": len(origins),
            "eligible_destinations": len(destinations),
            "sum_reverse_nodes_visited": visited_reverse,
            "sum_forward_nodes_visited": visited_forward,
            "maximum_total_walk_m": maximum_m,
            "walk_speed_m_min": speed_m_min,
        },
        "outputs": {
            str(ORIGIN_OUT.relative_to(ROOT)): {
                "rows": len(origin_pairs), "sha256": sha256(ORIGIN_OUT)
            },
            str(DESTINATION_OUT.relative_to(ROOT)): {
                "rows": len(destination_pairs), "sha256": sha256(DESTINATION_OUT)
            },
        },
    }
    METADATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    METADATA_OUT.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
