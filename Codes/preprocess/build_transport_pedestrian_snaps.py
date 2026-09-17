#!/usr/bin/env python3
"""Snap frozen origins, destinations and rail stops to the pedestrian graph."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "Codes/config/transport_pedestrian_graph.json"
GATE_CONFIG = ROOT / "Codes/config/transport_pedestrian_snap_gate.json"
NODES = ROOT / "Data/interim/transport/pedestrian_nodes.parquet"
GRID = ROOT / "Data/processed/transport/transport_grid_500m.parquet"
ORIGIN_WEIGHT = ROOT / "Data/processed/transport/worldpop_2023_origin_weights_500m.parquet"
DESTINATION = ROOT / "Data/processed/transport/worldpop_2023_destination_pixels.parquet"
STOPS = ROOT / "Data/interim/transport/d_route_stop_sequence_candidates.parquet"
ORIGIN_OUT = ROOT / "Data/interim/transport/pedestrian_origin_snaps_500m.parquet"
DESTINATION_OUT = ROOT / "Data/interim/transport/pedestrian_destination_snaps_worldpop2023.parquet"
STATION_OUT = ROOT / "Data/interim/transport/pedestrian_station_snaps.parquet"
METADATA_OUT = ROOT / "Data/metadata/transport/transport_pedestrian_snaps.json"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def snap_table(
    identifiers: pd.DataFrame,
    xy: np.ndarray,
    routing_nodes: pd.DataFrame,
    tree: cKDTree,
    maximum_m: float,
    second_extra_m: float,
) -> pd.DataFrame:
    distances, positions = tree.query(xy, k=2, workers=-1)
    first = routing_nodes.iloc[positions[:, 0]].reset_index(drop=True)
    second = routing_nodes.iloc[positions[:, 1]].reset_index(drop=True)
    output = identifiers.reset_index(drop=True).copy()
    output["nearest_node_index"] = first["node_index"].to_numpy()
    output["nearest_node_id"] = first["node_id"].to_numpy()
    output["nearest_distance_m"] = distances[:, 0]
    output["is_snapped"] = distances[:, 0] <= maximum_m
    output["second_node_index"] = second["node_index"].to_numpy()
    output["second_node_id"] = second["node_id"].to_numpy()
    output["second_distance_m"] = distances[:, 1]
    output["second_node_qualified"] = (
        (distances[:, 1] <= maximum_m)
        & ((distances[:, 1] - distances[:, 0]) <= second_extra_m)
    )
    output["routing_component_id"] = first["component_id"].to_numpy()
    return output


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    gate = json.loads(GATE_CONFIG.read_text(encoding="utf-8"))
    nodes = pd.read_parquet(NODES)
    routing_nodes = nodes.loc[nodes["is_largest_component"]].copy()
    if len(routing_nodes) < 2:
        raise RuntimeError("largest pedestrian component has fewer than two nodes")
    tree = cKDTree(routing_nodes[["x", "y"]].to_numpy())
    extra = cfg["snapping"]["second_nearest_variant_max_extra_network_m"]
    annual_stops = gpd.read_parquet(
        ROOT / gate["development_stage"]["union_station_source"]
    )
    union_stations = annual_stops.loc[
        annual_stops["passenger_service_active"]
    ].drop_duplicates(["sequence_id", "route_identity", "stop_order"])
    union_stations = union_stations.to_crs(cfg["network"]["crs"])
    union_station_tree = cKDTree(
        np.column_stack([union_stations.geometry.x, union_stations.geometry.y])
    )
    relevance_distance = gate["routing_relevance"][
        "necessary_euclidean_distance_m"
    ]

    grid = gpd.read_parquet(GRID)
    weights = pd.read_parquet(ORIGIN_WEIGHT)
    origin_geometry = grid.loc[
        grid["grid_id"].isin(weights["grid_id"]), ["grid_id", "geometry"]
    ].copy()
    if origin_geometry.crs != cfg["network"]["crs"]:
        origin_geometry = origin_geometry.to_crs(cfg["network"]["crs"])
    origin_geometry["geometry"] = origin_geometry.geometry.centroid
    origins = weights.merge(
        origin_geometry,
        on="grid_id",
        how="left",
        validate="one_to_one",
    )
    origins = gpd.GeoDataFrame(
        origins, geometry="geometry", crs=origin_geometry.crs
    )
    origin_xy = np.column_stack([origins.geometry.x, origins.geometry.y])
    origin_snaps = snap_table(
        origins.drop(columns="geometry"),
        origin_xy,
        routing_nodes,
        tree,
        cfg["snapping"]["origin_max_m"],
        extra,
    )
    origin_snaps["nearest_union_station_euclidean_m"] = union_station_tree.query(
        origin_xy, k=1, workers=-1
    )[0]
    origin_snaps["routing_relevant"] = origin_snaps[
        "nearest_union_station_euclidean_m"
    ].le(relevance_distance)

    destinations = gpd.read_parquet(DESTINATION)
    if destinations.crs != cfg["network"]["crs"]:
        destinations = destinations.to_crs(cfg["network"]["crs"])
    destination_xy = np.column_stack(
        [destinations.geometry.x, destinations.geometry.y]
    )
    destination_identifiers = destinations[
        ["pixel_id", "assigned_city", "population"]
    ].rename(columns={"assigned_city": "city"})
    destination_snaps = snap_table(
        destination_identifiers,
        destination_xy,
        routing_nodes,
        tree,
        cfg["snapping"]["destination_max_m"],
        extra,
    )
    destination_snaps[
        "nearest_union_station_euclidean_m"
    ] = union_station_tree.query(destination_xy, k=1, workers=-1)[0]
    destination_snaps["routing_relevant"] = destination_snaps[
        "nearest_union_station_euclidean_m"
    ].le(relevance_distance)

    stops = gpd.read_parquet(STOPS)
    if stops.crs != cfg["network"]["crs"]:
        stops = stops.to_crs(cfg["network"]["crs"])
    station_xy = np.column_stack([stops.geometry.x, stops.geometry.y])
    station_identifiers = stops[
        ["sequence_id", "route_identity", "stop_order", "station_name"]
    ]
    station_snaps = snap_table(
        station_identifiers,
        station_xy,
        routing_nodes,
        tree,
        cfg["snapping"]["station_max_m"],
        extra,
    )

    ORIGIN_OUT.parent.mkdir(parents=True, exist_ok=True)
    origin_snaps.to_parquet(ORIGIN_OUT, index=False)
    destination_snaps.to_parquet(DESTINATION_OUT, index=False)
    station_snaps.to_parquet(STATION_OUT, index=False)
    metadata = {
        "version": cfg["version"],
        "accessibility_outcome_read": False,
        "config_sha256": sha256(CONFIG),
        "snap_gate_config_sha256": sha256(GATE_CONFIG),
        "pedestrian_nodes_sha256": sha256(NODES),
        "routing_nodes": len(routing_nodes),
        "counts": {
            "origins": len(origin_snaps),
            "origins_snapped": int(origin_snaps["is_snapped"].sum()),
            "origins_routing_relevant": int(origin_snaps["routing_relevant"].sum()),
            "destinations": len(destination_snaps),
            "destinations_snapped": int(destination_snaps["is_snapped"].sum()),
            "destinations_routing_relevant": int(
                destination_snaps["routing_relevant"].sum()
            ),
            "stations": len(station_snaps),
            "stations_snapped": int(station_snaps["is_snapped"].sum()),
        },
        "outputs": {
            str(ORIGIN_OUT.relative_to(ROOT)): {
                "rows": len(origin_snaps), "sha256": sha256(ORIGIN_OUT)
            },
            str(DESTINATION_OUT.relative_to(ROOT)): {
                "rows": len(destination_snaps), "sha256": sha256(DESTINATION_OUT)
            },
            str(STATION_OUT.relative_to(ROOT)): {
                "rows": len(station_snaps), "sha256": sha256(STATION_OUT)
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
