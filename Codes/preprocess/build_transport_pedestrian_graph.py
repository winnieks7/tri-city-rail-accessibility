#!/usr/bin/env python3
"""Build the frozen contemporary pedestrian graph from an archived OSM PBF."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import osmium
import pandas as pd
from pyproj import Transformer
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.geometry import mapping


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "Codes/config/transport_pedestrian_graph.json"
BOUNDARIES = ROOT / "Data/interim/aoi/gba_city_boundaries.geojson"
AOI = ROOT / "Data/interim/transport/gba_nine_city_pedestrian_aoi.geojson"
CLIPPED_PBF = ROOT / "Data/interim/transport/gba_nine_city_pedestrian_complete_ways.osm.pbf"
NODES_OUT = ROOT / "Data/interim/transport/pedestrian_nodes.parquet"
EDGES_OUT = ROOT / "Data/interim/transport/pedestrian_edges.parquet"
METADATA_OUT = ROOT / "Data/metadata/transport/transport_pedestrian_graph.json"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


class WalkingWayHandler(osmium.SimpleHandler):
    """Collect only frozen walkable OSM way segments and referenced nodes."""

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        network = cfg["network"]
        self.included = set(network["included_highway_values"])
        self.excluded_access = set(network["excluded_access_values"])
        self.excluded_foot = set(network["excluded_foot_values"])
        self.foot_override = set(network["explicit_foot_override_values"])
        self.nodes: dict[int, tuple[float, float]] = {}
        self.segments: list[tuple] = []
        self.counts: Counter = Counter()

    def eligibility(self, tags: dict[str, str]) -> tuple[bool, str]:
        highway = tags.get("highway")
        if not highway:
            return False, "no_highway"
        if highway not in self.included:
            return False, "highway_not_in_frozen_inclusion_list"
        foot = tags.get("foot", "")
        if foot in self.excluded_foot:
            return False, "explicit_foot_restriction"
        if tags.get("access", "") in self.excluded_access and foot not in self.foot_override:
            return False, "access_restriction_without_foot_override"
        return True, "included"

    @staticmethod
    def directions(tags: dict[str, str]) -> tuple[bool, bool]:
        forward = True
        backward = True
        oneway_foot = tags.get("oneway:foot", "").lower()
        if oneway_foot in {"yes", "true", "1"}:
            backward = False
        elif oneway_foot in {"-1", "reverse"}:
            forward = False
        if tags.get("foot:forward", "").lower() in {"no", "private"}:
            forward = False
        if tags.get("foot:backward", "").lower() in {"no", "private"}:
            backward = False
        return forward, backward

    def way(self, way) -> None:  # pyosmium callback signature
        self.counts["ways_seen"] += 1
        tags = {tag.k: tag.v for tag in way.tags}
        eligible, reason = self.eligibility(tags)
        self.counts[reason] += 1
        if not eligible:
            return
        if len(way.nodes) < 2:
            self.counts["included_way_too_short"] += 1
            return
        forward, backward = self.directions(tags)
        if not forward and not backward:
            self.counts["included_way_no_allowed_direction"] += 1
            return
        locations = []
        for node in way.nodes:
            if not node.location.valid():
                self.counts["included_way_invalid_node_location"] += 1
                return
            locations.append((int(node.ref), float(node.location.lon), float(node.location.lat)))
        for node_id, lon, lat in locations:
            self.nodes[node_id] = (lon, lat)
        for first, second in zip(locations[:-1], locations[1:]):
            self.segments.append(
                (
                    int(way.id),
                    first[0],
                    second[0],
                    forward,
                    backward,
                    tags.get("highway", ""),
                    tags.get("bridge", "") not in {"", "no"},
                    tags.get("tunnel", "") not in {"", "no"},
                    tags.get("indoor", "") not in {"", "no"},
                )
            )
        self.counts["included_ways"] += 1
        self.counts["included_raw_segments"] += len(locations) - 1


def write_aoi(cfg: dict) -> None:
    boundaries = gpd.read_file(BOUNDARIES)
    selected = boundaries.loc[
        boundaries["gba_city"].isin(cfg["aoi"]["cities"])
    ].to_crs(cfg["network"]["crs"])
    if set(selected["gba_city"]) != set(cfg["aoi"]["cities"]):
        raise RuntimeError("pedestrian AOI is missing at least one frozen city")
    geometry = selected.geometry.union_all().buffer(cfg["aoi"]["buffer_m"])
    geometry_wgs = gpd.GeoSeries([geometry], crs=cfg["network"]["crs"]).to_crs(
        "EPSG:4326"
    ).iloc[0]
    feature = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": "GBA mainland nine-city pedestrian AOI",
                    "buffer_m": cfg["aoi"]["buffer_m"],
                },
                "geometry": mapping(geometry_wgs),
            }
        ],
    }
    AOI.parent.mkdir(parents=True, exist_ok=True)
    AOI.write_text(json.dumps(feature, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_complete_ways(source: Path) -> None:
    if CLIPPED_PBF.exists():
        return
    temporary = CLIPPED_PBF.with_suffix(CLIPPED_PBF.suffix + ".part")
    if temporary.exists():
        temporary.unlink()
    subprocess.run(
        [
            "osmium",
            "extract",
            "--strategy=complete_ways",
            "--polygon",
            str(AOI),
            "--output",
            str(temporary),
            "--output-format=pbf",
            str(source),
        ],
        check=True,
    )
    temporary.replace(CLIPPED_PBF)


def build_tables(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    handler = WalkingWayHandler(cfg)
    handler.apply_file(str(CLIPPED_PBF), locations=True)
    nodes = pd.DataFrame(
        [
            (node_id, lon, lat)
            for node_id, (lon, lat) in handler.nodes.items()
        ],
        columns=["node_id", "lon", "lat"],
    )
    edges = pd.DataFrame(
        handler.segments,
        columns=[
            "way_id", "raw_from_node", "raw_to_node", "raw_forward_allowed",
            "raw_backward_allowed", "highway", "is_bridge", "is_tunnel", "is_indoor",
        ],
    )
    if nodes.empty or edges.empty:
        raise RuntimeError("frozen pedestrian filter produced an empty graph")
    transformer = Transformer.from_crs(
        "EPSG:4326", cfg["network"]["crs"], always_xy=True
    )
    nodes["x"], nodes["y"] = transformer.transform(
        nodes["lon"].to_numpy(), nodes["lat"].to_numpy()
    )
    coordinates = nodes.set_index("node_id")[["x", "y"]]
    from_xy = coordinates.reindex(edges["raw_from_node"]).to_numpy()
    to_xy = coordinates.reindex(edges["raw_to_node"]).to_numpy()
    edges["length_m"] = np.hypot(
        from_xy[:, 0] - to_xy[:, 0], from_xy[:, 1] - to_xy[:, 1]
    )
    edges = edges.loc[np.isfinite(edges["length_m"]) & edges["length_m"].gt(0)].copy()
    swap = edges["raw_from_node"].gt(edges["raw_to_node"]).to_numpy()
    edges["from_node"] = np.where(
        swap, edges["raw_to_node"], edges["raw_from_node"]
    )
    edges["to_node"] = np.where(
        swap, edges["raw_from_node"], edges["raw_to_node"]
    )
    edges["forward_allowed"] = np.where(
        swap, edges["raw_backward_allowed"], edges["raw_forward_allowed"]
    )
    edges["backward_allowed"] = np.where(
        swap, edges["raw_forward_allowed"], edges["raw_backward_allowed"]
    )
    edges = (
        edges.groupby(["from_node", "to_node"], as_index=False)
        .agg(
            length_m=("length_m", "min"),
            forward_allowed=("forward_allowed", "max"),
            backward_allowed=("backward_allowed", "max"),
            representative_way_id=("way_id", "min"),
            highway=("highway", "first"),
            is_bridge=("is_bridge", "max"),
            is_tunnel=("is_tunnel", "max"),
            is_indoor=("is_indoor", "max"),
        )
        .sort_values(["from_node", "to_node"])
        .reset_index(drop=True)
    )
    retained_ids = np.union1d(edges["from_node"], edges["to_node"])
    nodes = nodes.loc[nodes["node_id"].isin(retained_ids)].sort_values("node_id").reset_index(drop=True)
    node_index = pd.Series(np.arange(len(nodes), dtype=np.int64), index=nodes["node_id"])
    edges["from_index"] = edges["from_node"].map(node_index).astype(np.int64)
    edges["to_index"] = edges["to_node"].map(node_index).astype(np.int64)
    adjacency = coo_matrix(
        (
            np.ones(len(edges), dtype=np.int8),
            (edges["from_index"].to_numpy(), edges["to_index"].to_numpy()),
        ),
        shape=(len(nodes), len(nodes)),
    )
    n_components, labels = connected_components(
        adjacency, directed=False, return_labels=True
    )
    component_sizes = np.bincount(labels)
    nodes["component_id"] = labels.astype(np.int32)
    nodes["component_node_count"] = component_sizes[labels].astype(np.int32)
    nodes["is_largest_component"] = labels == int(component_sizes.argmax())
    degree = np.bincount(
        np.concatenate([edges["from_index"].to_numpy(), edges["to_index"].to_numpy()]),
        minlength=len(nodes),
    )
    nodes["undirected_degree"] = degree.astype(np.int32)
    nodes.insert(0, "node_index", np.arange(len(nodes), dtype=np.int64))
    edges.insert(0, "edge_id", [f"walk_e{index:09d}" for index in range(len(edges))])
    metadata = {
        "filter_counts": dict(sorted(handler.counts.items())),
        "graph": {
            "nodes": len(nodes),
            "undirected_segments": len(edges),
            "explicitly_direction_restricted_segments": int(
                (~(edges["forward_allowed"] & edges["backward_allowed"])).sum()
            ),
            "components": int(n_components),
            "largest_component_nodes": int(component_sizes.max()),
            "largest_component_node_fraction": float(component_sizes.max() / len(nodes)),
            "total_segment_length_km": float(edges["length_m"].sum() / 1000),
        },
    }
    return nodes, edges, metadata


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    source = ROOT / cfg["source"]["path"]
    source_meta_path = ROOT / "Data/metadata/transport/guangdong_geofabrik_20260826.json"
    source_meta = json.loads(source_meta_path.read_text(encoding="utf-8"))
    if source.stat().st_size != cfg["source"]["expected_bytes"]:
        raise RuntimeError("archived Geofabrik byte count differs from frozen config")
    if source_meta["sha256"] != sha256(source):
        raise RuntimeError("archived Geofabrik hash differs from its metadata")
    write_aoi(cfg)
    extract_complete_ways(source)
    nodes, edges, details = build_tables(cfg)
    NODES_OUT.parent.mkdir(parents=True, exist_ok=True)
    nodes.to_parquet(NODES_OUT, index=False)
    edges.to_parquet(EDGES_OUT, index=False)
    result = {
        "version": cfg["version"],
        "accessibility_outcome_read": False,
        "config_sha256": sha256(CONFIG),
        "source": {
            "path": str(source.relative_to(ROOT)),
            "bytes": source.stat().st_size,
            "sha256": sha256(source),
            "md5": source_meta["md5"],
            "osm_replication_timestamp": source_meta[
                "pbf_header_and_extended_info"
            ]["header"]["option"]["osmosis_replication_timestamp"],
        },
        "interim": {
            str(AOI.relative_to(ROOT)): {"sha256": sha256(AOI)},
            str(CLIPPED_PBF.relative_to(ROOT)): {
                "bytes": CLIPPED_PBF.stat().st_size,
                "sha256": sha256(CLIPPED_PBF),
            },
        },
        **details,
        "outputs": {
            str(NODES_OUT.relative_to(ROOT)): {
                "rows": len(nodes), "sha256": sha256(NODES_OUT)
            },
            str(EDGES_OUT.relative_to(ROOT)): {
                "rows": len(edges), "sha256": sha256(EDGES_OUT)
            },
        },
    }
    METADATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    METADATA_OUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
