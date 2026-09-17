#!/usr/bin/env python3
"""Build and audit outcome-blind annual D-network geometry and topology."""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
from pyproj import Geod
from shapely.geometry import LineString


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "Codes/config/transport_d_annual_topology.json"
TRACK_EDGES = ROOT / "Data/interim/transport/d_route_track_edge_candidates.parquet"
STOPS = ROOT / "Data/interim/transport/d_route_stop_sequence_candidates.parquet"
OUT_EDGES = ROOT / "Data/interim/transport/d_annual_active_track_edges.parquet"
OUT_STOPS = ROOT / "Data/interim/transport/d_annual_active_passenger_stops.parquet"
OUT_CONNECTIONS = ROOT / "Data/interim/transport/d_annual_station_connection_pairs.parquet"
AUDIT = ROOT / "Results/pilots/transport_d_annual_topology_audit.json"
GEOD = Geod(ellps="WGS84")


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


def active_at_year_end(component: dict, year: int) -> bool:
    snapshot = datetime.fromisoformat(f"{year}-12-31T23:59:59+08:00")
    start = component.get("service_start_cst")
    end = component.get("service_end_cst")
    return bool(
        start
        and datetime.fromisoformat(start) <= snapshot
        and (end is None or snapshot < datetime.fromisoformat(end))
    )


def select_mapping_edges(
    mapping: dict, edges: gpd.GeoDataFrame, stops: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, dict]:
    sequence_id = mapping["sequence_id"]
    sequence_edges = edges.loc[edges["sequence_id"].eq(sequence_id)].copy()
    sequence_stops = stops.loc[stops["sequence_id"].eq(sequence_id)].copy()
    if mapping.get("all_edges"):
        return sequence_edges, {
            "component_id": mapping["component_id"],
            "sequence_id": sequence_id,
            "selection": "all_edges",
            "endpoint_match_count": None,
            "selected_edge_count": len(sequence_edges),
            "contiguous": len(sequence_edges) == max(len(sequence_stops) - 1, 0),
        }
    first = normalized_name(mapping["from_station"])
    second = normalized_name(mapping["to_station"])
    first_orders = sequence_stops.loc[
        sequence_stops["normalized_name"].eq(first), "stop_order"
    ].tolist()
    second_orders = sequence_stops.loc[
        sequence_stops["normalized_name"].eq(second), "stop_order"
    ].tolist()
    endpoint_match_count = len(first_orders) + len(second_orders)
    if len(first_orders) != 1 or len(second_orders) != 1:
        selected = sequence_edges.iloc[0:0].copy()
        contiguous = False
    else:
        low, high = sorted([int(first_orders[0]), int(second_orders[0])])
        selected = sequence_edges.loc[
            sequence_edges["from_order"].ge(low)
            & sequence_edges["to_order"].le(high)
        ].copy()
        contiguous = len(selected) == high - low
    return selected, {
        "component_id": mapping["component_id"],
        "sequence_id": sequence_id,
        "selection": f"{mapping['from_station']}--{mapping['to_station']}",
        "endpoint_match_count": endpoint_match_count,
        "selected_edge_count": len(selected),
        "contiguous": contiguous,
    }


def connection_distance(first: pd.Series, second: pd.Series) -> float:
    return float(
        GEOD.inv(first["lon"], first["lat"], second["lon"], second["lat"])[2]
    )


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    denominator_path = ROOT / config["denominator_config"]
    denominator = json.loads(denominator_path.read_text(encoding="utf-8"))
    components = {
        item["component_id"]: item for item in denominator["components"]
    }
    edges = gpd.read_parquet(TRACK_EDGES)
    stops = gpd.read_parquet(STOPS)

    selected_by_mapping: list[tuple[dict, gpd.GeoDataFrame]] = []
    mapping_audits = []
    for mapping in config["section_mappings"]:
        selected, mapping_audit = select_mapping_edges(mapping, edges, stops)
        selected_by_mapping.append((mapping, selected))
        mapping_audits.append(mapping_audit)

    active_edge_rows = []
    for year in config["years"]:
        for mapping, selected in selected_by_mapping:
            component = components[mapping["component_id"]]
            if not active_at_year_end(component, year):
                continue
            if year > mapping.get("active_through_year", year):
                continue
            for row in selected.itertuples(index=False):
                record = row._asdict()
                record.update(
                    {
                        "year": year,
                        "component_id": mapping["component_id"],
                        "activation_source": denominator_path.name,
                    }
                )
                active_edge_rows.append(record)

    active_edges = gpd.GeoDataFrame(
        active_edge_rows, geometry="geometry", crs=edges.crs
    )
    for rule in config["station_service_rules"]:
        if not rule.get("remove_incident_track_edges"):
            continue
        closed_names = {normalized_name(value) for value in rule["station_names"]}
        sequence_mask = active_edges["sequence_id"].eq(rule["sequence_id"])
        year_mask = active_edges["year"].ge(rule["closed_from_year"])
        incident_mask = active_edges["from_station"].map(normalized_name).isin(
            closed_names
        ) | active_edges["to_station"].map(normalized_name).isin(closed_names)
        active_edges = active_edges.loc[~(sequence_mask & year_mask & incident_mask)].copy()

    active_stop_keys: dict[int, set[tuple[str, int]]] = defaultdict(set)
    for row in active_edges.itertuples(index=False):
        active_stop_keys[int(row.year)].add((row.sequence_id, int(row.from_order)))
        active_stop_keys[int(row.year)].add((row.sequence_id, int(row.to_order)))

    stop_rows = []
    for year in config["years"]:
        for sequence_id, stop_order in sorted(active_stop_keys[year]):
            selected = stops.loc[
                stops["sequence_id"].eq(sequence_id)
                & stops["stop_order"].eq(stop_order)
            ]
            if len(selected) != 1:
                continue
            record = selected.iloc[0].to_dict()
            record["year"] = year
            record["passenger_service_active"] = True
            record["station_status_rule"] = "active_with_incident_section"
            stop_rows.append(record)
    annual_stops = gpd.GeoDataFrame(stop_rows, geometry="geometry", crs=stops.crs)

    rule_audits = []
    for rule in config["station_service_rules"]:
        component = components[rule["component_id"]]
        target_names = {normalized_name(value) for value in rule["station_names"]}
        target_mask = annual_stops["sequence_id"].eq(rule["sequence_id"]) & annual_stops[
            "normalized_name"
        ].isin(target_names)
        if rule["rule"] == "open_from_component_start":
            for year in config["years"]:
                if not active_at_year_end(component, year):
                    mask = target_mask & annual_stops["year"].eq(year)
                    annual_stops.loc[mask, "passenger_service_active"] = False
                    annual_stops.loc[mask, "station_status_rule"] = (
                        f"pass_through_closed_until_{component['service_start_cst']}"
                    )
        elif rule["rule"] == "closed_from_year":
            mask = target_mask & annual_stops["year"].ge(rule["closed_from_year"])
            annual_stops.loc[mask, "passenger_service_active"] = False
            annual_stops.loc[mask, "station_status_rule"] = (
                f"closed_from_{rule['closed_from_year']}"
            )
        rule_audits.append(
            {
                "component_id": rule["component_id"],
                "sequence_id": rule["sequence_id"],
                "target_station_names": sorted(target_names),
                "target_occurrence_count_all_years": int(target_mask.sum()),
                "rule": rule["rule"],
            }
        )

    alias_lookup: dict[str, set[str]] = defaultdict(set)
    for group in config["transfer_alias_groups"]:
        for name in group["station_names"]:
            alias_lookup[normalized_name(name)].add(group["alias_id"])

    connection_rows = []
    observed_aliases = set()
    for year, group in annual_stops.loc[
        annual_stops["passenger_service_active"]
    ].groupby("year"):
        records = [row for _, row in group.iterrows()]
        for first, second in itertools.combinations(records, 2):
            if first["sequence_id"] == second["sequence_id"]:
                continue
            exact_name = first["normalized_name"] == second["normalized_name"]
            aliases = alias_lookup[first["normalized_name"]] & alias_lookup[
                second["normalized_name"]
            ]
            if not exact_name and not aliases:
                continue
            distance_m = connection_distance(first, second)
            max_distance = (
                config["rules"]["same_name_connection_max_m"]
                if exact_name
                else config["rules"]["explicit_alias_connection_max_m"]
            )
            if distance_m > max_distance:
                continue
            observed_aliases.update(aliases)
            same_route = first["route_identity"] == second["route_identity"]
            first_mode = (
                "intercity" if "_IC" in first["route_identity"] else "urban"
            )
            second_mode = (
                "intercity" if "_IC" in second["route_identity"] else "urban"
            )
            both_intercity = first_mode == second_mode == "intercity"
            station_complex_id = (
                sorted(aliases)[0] if aliases else first["normalized_name"]
            )
            route_pair_id = "--".join(
                sorted([first["route_identity"], second["route_identity"]])
            )
            if same_route:
                connection_class = "same_route_pattern_continuity"
                transfer_stratum = None
                direct_walk_time_status = "not_applicable_same_route"
            elif both_intercity:
                connection_class = "intercity_junction_timetable_pending"
                transfer_stratum = None
                direct_walk_time_status = "pending_service_pattern_not_transfer_walk"
            else:
                connection_class = "passenger_transfer_candidate"
                transfer_stratum = (
                    "urban_intercity"
                    if "intercity" in {first_mode, second_mode}
                    else "urban_urban"
                )
                direct_walk_time_status = "pending_direct_verification_gate"
            connection_rows.append(
                {
                    "year": int(year),
                    "from_sequence_id": first["sequence_id"],
                    "from_stop_order": int(first["stop_order"]),
                    "from_route_identity": first["route_identity"],
                    "from_station": first["station_name"],
                    "to_sequence_id": second["sequence_id"],
                    "to_stop_order": int(second["stop_order"]),
                    "to_route_identity": second["route_identity"],
                    "to_station": second["station_name"],
                    "distance_m": distance_m,
                    "name_match": "exact" if exact_name else "explicit_alias",
                    "alias_ids": ";".join(sorted(aliases)),
                    "station_complex_id": station_complex_id,
                    "route_pair_id": route_pair_id,
                    "connection_pair_id": (
                        f"{int(year)}|{station_complex_id}|{route_pair_id}"
                    ),
                    "connection_class": connection_class,
                    "transfer_stratum": transfer_stratum,
                    "direct_walk_time_status": direct_walk_time_status,
                    "geometry": LineString([first.geometry, second.geometry]),
                }
            )
    connections = gpd.GeoDataFrame(
        connection_rows, geometry="geometry", crs=stops.crs
    )

    route_connectivity = []
    for (year, sequence_id), group in active_edges.groupby(["year", "sequence_id"]):
        graph = nx.Graph()
        for row in group.itertuples(index=False):
            graph.add_edge(int(row.from_order), int(row.to_order))
        route_connectivity.append(
            {
                "year": int(year),
                "sequence_id": sequence_id,
                "edge_count": len(group),
                "connected": bool(graph.number_of_nodes() and nx.is_connected(graph)),
            }
        )

    included_line_sections = {
        item["component_id"]
        for item in denominator["components"]
        if item["component_type"] == "line_section"
        and item["eligibility_status"] == "eligible"
    }
    mapped_line_sections = {
        item["component_id"] for item in config["section_mappings"]
    }
    included_station_changes = {
        item["component_id"]
        for item in denominator["components"]
        if item["component_type"] == "station_service_change"
        and item["eligibility_status"] == "eligible"
    }
    mapped_station_changes = {
        item["component_id"] for item in config["station_service_rules"]
    }
    expected_aliases = {
        item["alias_id"] for item in config["transfer_alias_groups"]
    }
    checks = {
        "outcome_data_not_read": config["rules"]["outcome_data_read"] is False,
        "all_eligible_line_sections_mapped": included_line_sections
        == mapped_line_sections,
        "all_station_service_changes_mapped": included_station_changes
        == mapped_station_changes,
        "all_mapping_endpoints_found_and_contiguous": all(
            item["selected_edge_count"] > 0 and item["contiguous"]
            for item in mapping_audits
        ),
        "all_active_edges_have_track_geometry": bool(
            len(active_edges) and active_edges.geometry.notna().all()
        ),
        "every_active_route_sequence_is_connected": all(
            item["connected"] for item in route_connectivity
        ),
        "all_station_rules_hit_occurrences": all(
            item["target_occurrence_count_all_years"] > 0 for item in rule_audits
        ),
        "all_explicit_alias_groups_observed": expected_aliases == observed_aliases,
        "all_connections_within_frozen_distance": bool(
            len(connections)
            and connections["distance_m"].le(
                max(
                    config["rules"]["same_name_connection_max_m"],
                    config["rules"]["explicit_alias_connection_max_m"],
                )
            ).all()
        ),
    }

    OUT_EDGES.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    active_edges.to_parquet(OUT_EDGES, index=False)
    annual_stops.to_parquet(OUT_STOPS, index=False)
    connections.to_parquet(OUT_CONNECTIONS, index=False)
    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit": "development_city_annual_geometry_and_topology",
        "config": str(CONFIG.relative_to(ROOT)),
        "config_sha256": sha256(CONFIG),
        "denominator_config": str(denominator_path.relative_to(ROOT)),
        "denominator_config_sha256": sha256(denominator_path),
        "sequence_config_sha256": sha256(ROOT / config["sequence_config"]),
        "track_edge_candidates_sha256": sha256(TRACK_EDGES),
        "stop_candidates_sha256": sha256(STOPS),
        "outcome_data_read": False,
        "included_line_section_count": len(included_line_sections),
        "mapped_line_section_count": len(mapped_line_sections),
        "included_station_change_count": len(included_station_changes),
        "mapped_station_change_count": len(mapped_station_changes),
        "annual_active_edge_rows": len(active_edges),
        "annual_stop_occurrence_rows": len(annual_stops),
        "annual_passenger_active_stop_occurrence_rows": int(
            annual_stops["passenger_service_active"].sum()
        ),
        "annual_connection_rows": len(connections),
        "annual_unique_passenger_transfer_pair_rows": int(
            connections.loc[
                connections["connection_class"].eq("passenger_transfer_candidate"),
                "connection_pair_id",
            ].nunique()
        ),
        "annual_unique_intercity_junction_pair_rows": int(
            connections.loc[
                connections["connection_class"].eq(
                    "intercity_junction_timetable_pending"
                ),
                "connection_pair_id",
            ].nunique()
        ),
        "connection_class_counts": connections["connection_class"].value_counts().to_dict(),
        "transfer_stratum_counts": connections["transfer_stratum"].value_counts().to_dict(),
        "observed_alias_groups": sorted(observed_aliases),
        "mapping_audits": mapping_audits,
        "station_rule_audits": rule_audits,
        "route_connectivity": route_connectivity,
        "checks": checks,
        "n_checks": len(checks),
        "n_passed": sum(checks.values()),
        "topology_gate_passed": all(checks.values()),
        "timetable_gate_passed": False,
        "outcome_access": "sealed",
        "outputs": {
            "annual_active_track_edges": str(OUT_EDGES.relative_to(ROOT)),
            "annual_active_passenger_stops": str(OUT_STOPS.relative_to(ROOT)),
            "annual_station_connection_pairs": str(OUT_CONNECTIONS.relative_to(ROOT)),
        },
        "output_sha256": {
            "annual_active_track_edges": sha256(OUT_EDGES),
            "annual_active_passenger_stops": sha256(OUT_STOPS),
            "annual_station_connection_pairs": sha256(OUT_CONNECTIONS),
        },
        "remaining_gate": "direct timetable and transfer-walk coverage plus frozen imputation donors",
    }
    AUDIT.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    raise SystemExit(0 if audit["topology_gate_passed"] else 1)


if __name__ == "__main__":
    main()
