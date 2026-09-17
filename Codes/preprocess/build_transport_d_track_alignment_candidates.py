#!/usr/bin/env python3
"""Build track-following edge candidates for the D-network stop sequences."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
from pyproj import Geod
from shapely.geometry import LineString


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "Codes/config/transport_d_route_sequence_sources.json"
STOPS = ROOT / "Data/interim/transport/d_route_stop_sequence_candidates.parquet"
OUT = ROOT / "Data/interim/transport/d_route_track_edge_candidates.parquet"
AUDIT = ROOT / "Results/pilots/transport_d_track_alignment_candidate_audit.json"
GEOD = Geod(ellps="WGS84")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def coordinate_key(lon: float, lat: float) -> tuple[float, float]:
    return round(float(lon), 7), round(float(lat), 7)


def way_coordinates(element: dict) -> list[tuple[float, float]]:
    return [
        coordinate_key(node["lon"], node["lat"])
        for node in element.get("geometry", [])
        if "lon" in node and "lat" in node
    ]


def relation_way_elements(index: dict, relation_id: int) -> list[dict]:
    relation = index.get(("relation", int(relation_id)))
    if relation is None:
        return []
    rows = []
    for member in relation.get("members", []):
        if member.get("type") != "way":
            continue
        element = index.get(("way", int(member["ref"])))
        if element is not None and len(way_coordinates(element)) >= 2:
            rows.append(element)
    return rows


def geod_distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return float(GEOD.inv(first[0], first[1], second[0], second[1])[2])


def build_graph(ways: list[dict]) -> nx.Graph:
    graph = nx.Graph()
    for way in ways:
        coordinates = way_coordinates(way)
        for first, second in zip(coordinates, coordinates[1:]):
            if first == second:
                continue
            distance = geod_distance(first, second)
            previous = graph.get_edge_data(first, second)
            if previous is None or distance < previous["length_m"]:
                graph.add_edge(
                    first,
                    second,
                    length_m=distance,
                    osm_way_id=int(way["id"]),
                )
    return graph


def largest_component(graph: nx.Graph) -> nx.Graph:
    if graph.number_of_nodes() == 0:
        return graph
    component = max(nx.connected_components(graph), key=len)
    return graph.subgraph(component).copy()


def nearby_nodes(
    nodes: np.ndarray,
    station_lon: float,
    station_lat: float,
    *,
    minimum_radius_m: float = 30.0,
    extra_radius_m: float = 25.0,
    maximum_candidates: int = 64,
) -> list[tuple[tuple[float, float], float]]:
    """Return plausible track attachments on both sides of a multi-track line.

    A single nearest node can alternate between parallel running tracks.  If those
    tracks connect only at a distant crossover or terminal, independent nearest
    snapping creates a false out-and-back path.  The adaptive radius retains the
    nearest attachment while also exposing nearby nodes on the parallel track.
    """
    scale_x = 111_320.0 * math.cos(math.radians(station_lat))
    dx = (nodes[:, 0] - station_lon) * scale_x
    dy = (nodes[:, 1] - station_lat) * 110_574.0
    distances = np.hypot(dx, dy)
    ordered = np.argsort(distances)
    nearest_distance = float(distances[int(ordered[0])])
    radius = max(minimum_radius_m, nearest_distance + extra_radius_m)
    selected = [int(position) for position in ordered if distances[position] <= radius]
    selected = selected[:maximum_candidates] or [int(ordered[0])]
    return [
        (
            (float(nodes[position, 0]), float(nodes[position, 1])),
            float(distances[position]),
        )
        for position in selected
    ]


def best_track_path(
    graph: nx.Graph,
    first_candidates: list[tuple[tuple[float, float], float]],
    second_candidates: list[tuple[tuple[float, float], float]],
    edge_key: str,
) -> tuple[list[tuple[float, float]], float, float] | None:
    """Find the track path minimizing track distance plus both snap distances."""
    source = ("__virtual_source__", edge_key)
    target = ("__virtual_target__", edge_key)
    for node, distance in first_candidates:
        graph.add_edge(source, node, length_m=distance, osm_way_id=-1)
    for node, distance in second_candidates:
        graph.add_edge(node, target, length_m=distance, osm_way_id=-1)
    try:
        full_path = nx.shortest_path(graph, source, target, weight="length_m")
        if len(full_path) < 4:
            return None
        track_nodes = full_path[1:-1]
        first_snap = float(graph.edges[source, track_nodes[0]]["length_m"])
        second_snap = float(graph.edges[track_nodes[-1], target]["length_m"])
        return track_nodes, first_snap, second_snap
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    finally:
        graph.remove_nodes_from([source, target])


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    main_path = ROOT / config["relation_snapshot"]
    main_raw = json.loads(main_path.read_text(encoding="utf-8"))
    main_index = {
        (item["type"], int(item["id"])): item for item in main_raw["elements"]
    }
    supplemental = {}
    supplemental_records = []
    for item in config.get("supplemental_geometry_snapshots", []):
        path = ROOT / item["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        index = {
            (element["type"], int(element["id"])): element
            for element in payload.get("elements", [])
        }
        supplemental[item["route_identity"]] = (path, payload, index)
        supplemental_records.append(
            {
                "route_identity": item["route_identity"],
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path),
            }
        )

    stops = gpd.read_parquet(STOPS)
    edge_rows = []
    summaries = []
    for sequence in config["sequences"]:
        sequence_id = sequence["sequence_id"]
        route_identity = sequence["route_identity"]
        relation_ids = []
        if "relation_id" in sequence:
            relation_ids.append(int(sequence["relation_id"]))
        relation_ids.extend(int(value) for value in sequence.get("coordinate_relation_ids", []))
        ways_by_id = {}
        for relation_id in relation_ids:
            for way in relation_way_elements(main_index, relation_id):
                ways_by_id[int(way["id"])] = way

        supplemental_path = None
        if route_identity in supplemental:
            supplemental_path, payload, supplemental_index = supplemental[route_identity]
            supplemental_relations = [
                element
                for element in payload.get("elements", [])
                if element.get("type") == "relation"
            ]
            for relation in supplemental_relations:
                for way in relation_way_elements(
                    supplemental_index, int(relation["id"])
                ):
                    ways_by_id[int(way["id"])] = way
            for way in payload.get("elements", []):
                tags = way.get("tags") or {}
                if (
                    way.get("type") == "way"
                    and tags.get("railway") in {"rail", "subway", "light_rail", "tram"}
                    and tags.get("service") not in {"yard", "siding", "spur"}
                    and len(way_coordinates(way)) >= 2
                ):
                    ways_by_id[int(way["id"])] = way

        graph_all = build_graph(list(ways_by_id.values()))
        graph = largest_component(graph_all)
        node_array = np.asarray(list(graph.nodes), dtype=float)
        sequence_stops = stops.loc[stops["sequence_id"].eq(sequence_id)].sort_values(
            "stop_order"
        )
        snap_rows = []
        if len(node_array):
            for row in sequence_stops.itertuples(index=False):
                candidates = nearby_nodes(
                    node_array, float(row.lon), float(row.lat)
                )
                snap_rows.append((row, candidates))

        path_failures = []
        sequence_length_m = 0.0
        selected_snap_distances = []
        for (first, first_candidates), (second, second_candidates) in zip(
            snap_rows, snap_rows[1:]
        ):
            best_path = best_track_path(
                graph,
                first_candidates,
                second_candidates,
                f"{sequence_id}:{int(first.stop_order)}:{int(second.stop_order)}",
            )
            path_nodes = best_path[0] if best_path is not None else None
            first_snap = best_path[1] if best_path is not None else None
            second_snap = best_path[2] if best_path is not None else None
            if best_path is None:
                path_failures.append(f"{first.station_name}->{second.station_name}")
            geometry = None
            length_m = None
            way_ids = []
            if path_nodes and len(path_nodes) >= 2:
                geometry = LineString(path_nodes)
                length_m = sum(
                    float(graph.edges[a, b]["length_m"])
                    for a, b in zip(path_nodes, path_nodes[1:])
                )
                way_ids = sorted(
                    {
                        int(graph.edges[a, b]["osm_way_id"])
                        for a, b in zip(path_nodes, path_nodes[1:])
                    }
                )
                sequence_length_m += length_m
                selected_snap_distances.extend([first_snap, second_snap])
            edge_rows.append(
                {
                    "sequence_id": sequence_id,
                    "route_identity": route_identity,
                    "from_order": int(first.stop_order),
                    "to_order": int(second.stop_order),
                    "from_station": first.station_name,
                    "to_station": second.station_name,
                    "from_snap_distance_m": first_snap,
                    "to_snap_distance_m": second_snap,
                    "track_length_m": length_m,
                    "osm_way_ids": ";".join(map(str, way_ids)),
                    "geometry_role": "track_following_candidate",
                    "geometry": geometry,
                }
            )

        nearest_snap_distances = [item[1][0][1] for item in snap_rows]
        summaries.append(
            {
                "sequence_id": sequence_id,
                "route_identity": route_identity,
                "source_relation_ids": relation_ids,
                "supplemental_snapshot": (
                    str(supplemental_path.relative_to(ROOT))
                    if supplemental_path is not None
                    else None
                ),
                "source_way_count": len(ways_by_id),
                "all_graph_node_count": graph_all.number_of_nodes(),
                "largest_component_node_count": graph.number_of_nodes(),
                "largest_component_fraction": (
                    graph.number_of_nodes() / graph_all.number_of_nodes()
                    if graph_all.number_of_nodes()
                    else 0.0
                ),
                "station_count": len(sequence_stops),
                "station_snap_count": len(snap_rows),
                "max_station_snap_distance_m": (
                    max(selected_snap_distances) if selected_snap_distances else None
                ),
                "median_station_snap_distance_m": (
                    float(np.median(selected_snap_distances))
                    if selected_snap_distances
                    else None
                ),
                "max_nearest_track_distance_m": (
                    max(nearest_snap_distances) if nearest_snap_distances else None
                ),
                "edge_count": max(len(sequence_stops) - 1, 0),
                "path_failure_count": len(path_failures),
                "path_failures": path_failures,
                "candidate_track_length_km": sequence_length_m / 1000.0,
                "candidate_pass": bool(
                    len(snap_rows) == len(sequence_stops)
                    and selected_snap_distances
                    and max(selected_snap_distances) <= 500.0
                    and not path_failures
                ),
            }
        )

    edges = gpd.GeoDataFrame(edge_rows, geometry="geometry", crs="EPSG:4326")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    edges.to_parquet(OUT, index=False)
    passed = sum(item["candidate_pass"] for item in summaries)
    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit": "development_city_track_alignment_candidates",
        "config": str(CONFIG.relative_to(ROOT)),
        "config_sha256": sha256(CONFIG),
        "stop_candidates": str(STOPS.relative_to(ROOT)),
        "stop_candidates_sha256": sha256(STOPS),
        "main_relation_snapshot": str(main_path.relative_to(ROOT)),
        "main_relation_snapshot_sha256": sha256(main_path),
        "supplemental_snapshots": supplemental_records,
        "outcome_data_read": False,
        "sequence_count": len(summaries),
        "candidate_pass_count": passed,
        "candidate_fail_count": len(summaries) - passed,
        "track_edge_count": len(edges),
        "all_edges_have_track_geometry": bool(edges.geometry.notna().all()),
        "path_method": "adaptive multi-track attachment minimizing track plus endpoint snap distance",
        "summaries": summaries,
        "output": str(OUT.relative_to(ROOT)),
        "geometry_gate_passed": False,
        "remaining_gate": (
            "manual review of failed/large-snap alignments, annual activation and transfer topology"
            if passed != len(summaries) or not edges.geometry.notna().all()
            else "freeze audited alignment hashes, then apply annual activation and transfer topology"
        ),
    }
    AUDIT.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
