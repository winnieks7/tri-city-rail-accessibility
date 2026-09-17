#!/usr/bin/env python3
"""Build outcome-blind D-network passenger-stop and straight-edge candidates.

Current OSM relations supply locatable coordinates and candidate order. The
frozen config trims later extensions and replaces unstable intercity relation
order with official 2018--2024 sequences. These outputs are engineering
candidates, not a passed historical topology gate.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "Codes/config/transport_d_route_sequence_sources.json"
OUT_STOPS = ROOT / "Data/interim/transport/d_route_stop_sequence_candidates.parquet"
OUT_EDGES = ROOT / "Data/interim/transport/d_route_straight_edge_candidates.parquet"
OUT_AUDIT = ROOT / "Results/pilots/transport_d_route_sequence_candidate_audit.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_name(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().replace(" ", "")
    if text.endswith("站") and text not in {"广州站"}:
        text = text[:-1]
    return text


def element_coordinate(element: dict) -> tuple[float, float] | None:
    if "lon" in element and "lat" in element:
        return float(element["lon"]), float(element["lat"])
    center = element.get("center") or {}
    if "lon" in center and "lat" in center:
        return float(center["lon"]), float(center["lat"])
    geometry = element.get("geometry") or []
    coordinates = [
        (float(node["lon"]), float(node["lat"]))
        for node in geometry
        if "lon" in node and "lat" in node
    ]
    if coordinates:
        return (
            sum(item[0] for item in coordinates) / len(coordinates),
            sum(item[1] for item in coordinates) / len(coordinates),
        )
    return None


def relation_stops(index: dict, relation_id: int) -> list[dict]:
    relation = index.get(("relation", int(relation_id)))
    if relation is None:
        return []
    rows: list[dict] = []
    for member in relation.get("members", []):
        if not str(member.get("role", "")).startswith("stop"):
            continue
        element = index.get((member["type"], int(member["ref"])), {})
        tags = element.get("tags") or {}
        name = tags.get("name") or tags.get("name:zh")
        coordinate = element_coordinate(element) or element_coordinate(member)
        if not name:
            continue
        if rows and normalized_name(rows[-1]["name"]) == normalized_name(name):
            continue
        rows.append(
            {
                "name": str(name),
                "normalized_name": normalized_name(name),
                "coordinate": coordinate,
                "osm_type": member["type"],
                "osm_id": int(member["ref"]),
            }
        )
    return rows


def trim_between(stops: list[dict], endpoints: list[str]) -> list[dict]:
    normalized = [item["normalized_name"] for item in stops]
    start, end = map(normalized_name, endpoints)
    if start not in normalized or end not in normalized:
        return []
    left = normalized.index(start)
    right = normalized.index(end)
    if left <= right:
        return stops[left : right + 1]
    return list(reversed(stops[right : left + 1]))


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    relation_path = ROOT / config["relation_snapshot"]
    station_path = ROOT / config["station_snapshot"]
    raw = json.loads(relation_path.read_text(encoding="utf-8"))
    index = {(item["type"], int(item["id"])): item for item in raw["elements"]}
    stations = gpd.read_parquet(station_path)
    stations["normalized_name"] = stations["name"].map(normalized_name)

    relation_cache = {
        int(item["relation_id"]): relation_stops(index, int(item["relation_id"]))
        for item in config["sequences"]
        if "relation_id" in item
    }
    global_relation_name_index: dict[str, list[dict]] = defaultdict(list)
    for relation_id in {
        int(value)
        for item in config["sequences"]
        for value in ([item["relation_id"]] if "relation_id" in item else item.get("coordinate_relation_ids", []))
    }:
        for stop in relation_stops(index, relation_id):
            global_relation_name_index[stop["normalized_name"]].append(
                {**stop, "relation_id": relation_id}
            )
    supplemental_name_index: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    supplemental_snapshot_records: list[dict] = []
    for snapshot in config.get("supplemental_geometry_snapshots", []):
        snapshot_path = ROOT / snapshot["path"]
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        supplemental_snapshot_records.append(
            {
                "route_identity": snapshot["route_identity"],
                "path": str(snapshot_path.relative_to(ROOT)),
                "sha256": sha256(snapshot_path),
            }
        )
        for element in payload.get("elements", []):
            tags = element.get("tags") or {}
            name = tags.get("name") or tags.get("name:zh")
            coordinate = element_coordinate(element)
            if not name or coordinate is None:
                continue
            public_transport = tags.get("public_transport")
            priority = 0
            if element.get("type") == "node" and public_transport == "station":
                priority = 3
            elif element.get("type") == "node" and public_transport == "stop_position":
                priority = 2
            elif public_transport == "platform":
                priority = 1
            supplemental_name_index[snapshot["route_identity"]][
                normalized_name(name)
            ].append(
                {
                    "coordinate": coordinate,
                    "osm_type": element.get("type"),
                    "osm_id": int(element["id"]),
                    "priority": priority,
                    "source_path": str(snapshot_path.relative_to(ROOT)),
                }
            )

    stop_rows: list[dict] = []
    summaries: list[dict] = []
    for sequence in config["sequences"]:
        source = sequence["source"]
        endpoint_pass = True
        insertion_pass = True
        if source.startswith("current_relation"):
            raw_stops = relation_cache.get(int(sequence["relation_id"]), [])
            if "keep_between" in sequence:
                selected = trim_between(raw_stops, sequence["keep_between"])
                endpoint_pass = bool(selected)
            else:
                selected = raw_stops
            exclusions = {
                normalized_name(value)
                for value in sequence.get("exclude_passenger_stops", [])
            }
            selected = [
                item for item in selected if item["normalized_name"] not in exclusions
            ]
            for insertion in sequence.get("insert_stops", []):
                insertion_name = insertion["name"]
                insertion_norm = normalized_name(insertion_name)
                preferred_relations = {
                    int(value)
                    for value in insertion.get(
                        "coordinate_relation_ids",
                        sequence.get("coordinate_relation_ids", []),
                    )
                }
                relation_candidates = [
                    item
                    for item in global_relation_name_index.get(insertion_norm, [])
                    if preferred_relations
                    and int(item["relation_id"]) in preferred_relations
                    and item["coordinate"] is not None
                ]
                station_candidates = stations.loc[
                    stations["normalized_name"].eq(insertion_norm)
                ]
                coordinate_bbox = insertion.get("coordinate_bbox")
                if coordinate_bbox and len(station_candidates):
                    west, south, east, north = coordinate_bbox
                    station_candidates = station_candidates.loc[
                        station_candidates.geometry.x.between(west, east)
                        & station_candidates.geometry.y.between(south, north)
                    ]
                inserted_stop = None
                if relation_candidates:
                    candidate = relation_candidates[0]
                    inserted_stop = {
                        "name": insertion_name,
                        "normalized_name": insertion_norm,
                        "coordinate": candidate["coordinate"],
                        "coordinate_source": f"relation_{candidate['relation_id']}",
                        "osm_type": candidate["osm_type"],
                        "osm_id": candidate["osm_id"],
                    }
                elif len(station_candidates):
                    candidate = station_candidates.iloc[0]
                    inserted_stop = {
                        "name": insertion_name,
                        "normalized_name": insertion_norm,
                        "coordinate": (
                            float(candidate.geometry.x),
                            float(candidate.geometry.y),
                        ),
                        "coordinate_source": "gba_station_snapshot_historical_insertion",
                        "osm_type": candidate["osm_type"],
                        "osm_id": int(candidate["osm_id"]),
                    }
                normalized_selected = [
                    item["normalized_name"] for item in selected
                ]
                if inserted_stop is None:
                    insertion_pass = False
                    continue
                if "before" in insertion:
                    anchor = normalized_name(insertion["before"])
                    if anchor not in normalized_selected:
                        insertion_pass = False
                        continue
                    selected.insert(normalized_selected.index(anchor), inserted_stop)
                elif "after" in insertion:
                    anchor = normalized_name(insertion["after"])
                    if anchor not in normalized_selected:
                        insertion_pass = False
                        continue
                    selected.insert(normalized_selected.index(anchor) + 1, inserted_stop)
                else:
                    insertion_pass = False
        else:
            selected = []
            preferred_relations = {
                int(value) for value in sequence.get("coordinate_relation_ids", [])
            }
            coordinate_bbox = sequence.get("coordinate_bbox")
            for official_name in sequence["official_sequence"]:
                norm = normalized_name(official_name)
                relation_candidates = [
                    item
                    for item in global_relation_name_index.get(norm, [])
                    if preferred_relations
                    and int(item["relation_id"]) in preferred_relations
                ]
                station_candidates = stations.loc[
                    stations["normalized_name"].eq(norm)
                ]
                if coordinate_bbox and len(station_candidates):
                    west, south, east, north = coordinate_bbox
                    station_candidates = station_candidates.loc[
                        station_candidates.geometry.x.between(west, east)
                        & station_candidates.geometry.y.between(south, north)
                    ]
                coordinate = None
                coordinate_source = "missing"
                osm_type = None
                osm_id = None
                supplemental_candidates = supplemental_name_index[
                    sequence["route_identity"]
                ].get(norm, [])
                if supplemental_candidates:
                    candidate = sorted(
                        supplemental_candidates,
                        key=lambda item: (-item["priority"], item["osm_id"]),
                    )[0]
                    coordinate = candidate["coordinate"]
                    coordinate_source = f"supplemental:{candidate['source_path']}"
                    osm_type = candidate["osm_type"]
                    osm_id = candidate["osm_id"]
                elif relation_candidates:
                    candidate = next(
                        (
                            item
                            for item in relation_candidates
                            if item["coordinate"] is not None
                        ),
                        relation_candidates[0],
                    )
                    coordinate = candidate["coordinate"]
                    coordinate_source = f"relation_{candidate['relation_id']}"
                    osm_type = candidate["osm_type"]
                    osm_id = candidate["osm_id"]
                elif len(station_candidates):
                    candidate = station_candidates.iloc[0]
                    coordinate = (float(candidate.geometry.x), float(candidate.geometry.y))
                    coordinate_source = "gba_station_snapshot"
                    osm_type = candidate["osm_type"]
                    osm_id = int(candidate["osm_id"])
                selected.append(
                    {
                        "name": official_name,
                        "normalized_name": norm,
                        "coordinate": coordinate,
                        "coordinate_source": coordinate_source,
                        "osm_type": osm_type,
                        "osm_id": osm_id,
                    }
                )

        year_end_exclusions = {
            normalized_name(value)
            for value in sequence.get("2024_year_end_excluded_passenger_stops", [])
        }
        sequence_rows: list[dict] = []
        for order, stop in enumerate(selected, start=1):
            coordinate = stop.get("coordinate")
            coordinate_source = stop.get(
                "coordinate_source", f"relation_{sequence.get('relation_id')}"
            )
            row = {
                "sequence_id": sequence["sequence_id"],
                "route_identity": sequence["route_identity"],
                "stop_order": order,
                "station_name": stop["name"],
                "normalized_name": stop["normalized_name"],
                "passenger_stop_at_2024_year_end": (
                    stop["normalized_name"] not in year_end_exclusions
                ),
                "coordinate_source": coordinate_source,
                "osm_type": stop.get("osm_type"),
                "osm_id": stop.get("osm_id"),
                "lon": coordinate[0] if coordinate else None,
                "lat": coordinate[1] if coordinate else None,
                "geometry": Point(coordinate) if coordinate else None,
            }
            sequence_rows.append(row)
            stop_rows.append(row)

        unique_stop_count = len({row["normalized_name"] for row in sequence_rows})
        expected_count = sequence.get("expected_unique_stop_count")
        summaries.append(
            {
                "sequence_id": sequence["sequence_id"],
                "route_identity": sequence["route_identity"],
                "source": source,
                "stop_occurrence_count": len(sequence_rows),
                "unique_stop_count": unique_stop_count,
                "coordinate_complete_count": sum(
                    row["geometry"] is not None for row in sequence_rows
                ),
                "missing_coordinate_names": [
                    row["station_name"]
                    for row in sequence_rows
                    if row["geometry"] is None
                ],
                "endpoint_trim_passed": endpoint_pass,
                "historical_insertion_passed": insertion_pass,
                "expected_unique_stop_count_passed": (
                    expected_count is None or unique_stop_count == expected_count
                ),
            }
        )

    stops = gpd.GeoDataFrame(stop_rows, geometry="geometry", crs="EPSG:4326")
    edge_rows: list[dict] = []
    for sequence_id, group in stops.groupby("sequence_id", sort=False):
        ordered = group.sort_values("stop_order")
        records = list(ordered.to_dict("records"))
        for first, second in zip(records, records[1:]):
            geometry = None
            if first["geometry"] is not None and second["geometry"] is not None:
                geometry = LineString([first["geometry"], second["geometry"]])
            edge_rows.append(
                {
                    "sequence_id": sequence_id,
                    "route_identity": first["route_identity"],
                    "from_order": int(first["stop_order"]),
                    "to_order": int(second["stop_order"]),
                    "from_station": first["station_name"],
                    "to_station": second["station_name"],
                    "geometry_role": "straight_topology_candidate_not_track_alignment",
                    "geometry": geometry,
                }
            )
    edges = gpd.GeoDataFrame(edge_rows, geometry="geometry", crs="EPSG:4326")

    OUT_STOPS.parent.mkdir(parents=True, exist_ok=True)
    OUT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    stops.to_parquet(OUT_STOPS, index=False)
    edges.to_parquet(OUT_EDGES, index=False)
    all_endpoints_pass = all(item["endpoint_trim_passed"] for item in summaries)
    all_expected_counts_pass = all(
        item["expected_unique_stop_count_passed"] for item in summaries
    )
    all_historical_insertions_pass = all(
        item["historical_insertion_passed"] for item in summaries
    )
    missing_coordinates = sum(
        len(item["missing_coordinate_names"]) for item in summaries
    )
    blocking_reasons = []
    if missing_coordinates:
        blocking_reasons.append(
            "missing station coordinates must be independently located"
        )
    if not all_historical_insertions_pass:
        blocking_reasons.append(
            "one or more predeclared historical station insertions could not be located"
        )
    blocking_reasons.extend(
        [
            "straight station links are topology candidates, not frozen track alignments",
            "annual component activation and transfer-pair connectivity are not yet applied",
        ]
    )
    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit": "development_city_route_sequence_candidates",
        "config": str(CONFIG.relative_to(ROOT)),
        "config_sha256": sha256(CONFIG),
        "relation_snapshot": str(relation_path.relative_to(ROOT)),
        "relation_snapshot_sha256": sha256(relation_path),
        "station_snapshot": str(station_path.relative_to(ROOT)),
        "station_snapshot_sha256": sha256(station_path),
        "supplemental_geometry_snapshots": supplemental_snapshot_records,
        "outcome_data_read": False,
        "sequence_count": len(summaries),
        "route_identity_count": len({item["route_identity"] for item in summaries}),
        "stop_occurrence_count": len(stops),
        "straight_edge_count": len(edges),
        "all_endpoint_trims_passed": all_endpoints_pass,
        "all_historical_insertions_passed": all_historical_insertions_pass,
        "all_expected_stop_counts_passed": all_expected_counts_pass,
        "missing_coordinate_occurrence_count": missing_coordinates,
        "summaries": summaries,
        "outputs": [
            str(OUT_STOPS.relative_to(ROOT)),
            str(OUT_EDGES.relative_to(ROOT)),
        ],
        "geometry_gate_passed": False,
        "blocking_reasons": blocking_reasons,
    }
    OUT_AUDIT.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
