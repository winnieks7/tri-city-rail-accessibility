#!/usr/bin/env python3
"""Build arbitrary annual D-network event-coalition states without outcomes."""

from __future__ import annotations

import itertools
import json
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Geod


ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "Codes/config/transport_d_event_packages.json"
TOPOLOGY = ROOT / "Codes/config/transport_d_annual_topology_20260826_r1.json"
COMPONENTS = ROOT / "Codes/config/transport_d_network_denominator_candidates_20260826_r5.json"
ANNUAL_EDGES = ROOT / "Data/interim/transport/d_annual_active_track_edges.parquet"
CANDIDATE_STOPS = ROOT / "Data/interim/transport/d_route_stop_sequence_candidates.parquet"
GEOD = Geod(ellps="WGS84")
EDGE_KEY = ["sequence_id", "route_identity", "component_id", "from_order", "to_order"]
STOP_KEY = ["sequence_id", "route_identity", "stop_order"]


def normalized_name(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip().replace(" ", "")
    if text.endswith("站") and text not in {"广州站"}:
        text = text[:-1]
    return text


class FrozenEventStateBuilder:
    """Reconstruct edge, passenger-stop and transfer state for one coalition."""

    def __init__(self) -> None:
        self.event_config = json.loads(EVENTS.read_text(encoding="utf-8"))
        self.topology = json.loads(TOPOLOGY.read_text(encoding="utf-8"))
        mother = json.loads(COMPONENTS.read_text(encoding="utf-8"))
        self.components = {item["component_id"]: item for item in mother["components"]}
        self.edges = gpd.read_parquet(ANNUAL_EDGES)
        self.candidate_stops = gpd.read_parquet(CANDIDATE_STOPS)
        self.packages = {
            item["event_id"]: item for item in self.event_config["packages"]
        }
        self.packages_by_year = {
            year: [
                item for item in self.event_config["packages"] if item["year"] == year
            ]
            for year in range(2018, 2025)
        }
        self.station_rules = {
            item["component_id"]: item
            for item in self.topology["station_service_rules"]
        }
        self.alias_lookup: dict[str, set[str]] = {}
        for group in self.topology["transfer_alias_groups"]:
            for name in group["station_names"]:
                self.alias_lookup.setdefault(normalized_name(name), set()).add(
                    group["alias_id"]
                )

    def _validate_coalition(self, year: int, included_event_ids: set[str]) -> list[dict]:
        available = {item["event_id"] for item in self.packages_by_year[year]}
        if not included_event_ids <= available:
            raise ValueError("coalition contains an event outside the requested year")
        return [
            item
            for item in self.packages_by_year[year]
            if item["event_id"] in included_event_ids
        ]

    def build_edges(self, year: int, included_event_ids: set[str]) -> gpd.GeoDataFrame:
        selected = self._validate_coalition(year, included_event_ids)
        state = self.edges.loc[self.edges["year"].eq(year - 1)].copy()
        target = self.edges.loc[self.edges["year"].eq(year)].copy()
        for package in selected:
            for component_id in package.get("add_components", []):
                additions = target.loc[target["component_id"].eq(component_id)]
                if len(additions):
                    state = gpd.GeoDataFrame(
                        pd.concat([state, additions], ignore_index=True),
                        geometry="geometry",
                        crs=self.edges.crs,
                    )
            for component_id in package.get("remove_components", []):
                if self.components[component_id]["component_type"] == "line_section":
                    state = state.loc[~state["component_id"].eq(component_id)].copy()
            for replacement in package.get("sequence_replacements", []):
                mask = state["component_id"].eq(replacement["component_id"]) & state[
                    "sequence_id"
                ].isin(replacement["remove_sequence_ids"])
                state = state.loc[~mask].copy()
            closure = package.get("station_closure_rule")
            if closure and closure["remove_incident_track_edges"]:
                closed = {normalized_name(name) for name in closure["station_names"]}
                incident = state["sequence_id"].eq(closure["sequence_id"]) & (
                    state["from_station"].map(normalized_name).isin(closed)
                    | state["to_station"].map(normalized_name).isin(closed)
                )
                state = state.loc[~incident].copy()
        state = state.drop_duplicates(EDGE_KEY).copy()
        state["year"] = year
        return state.sort_values(EDGE_KEY).reset_index(drop=True)

    def build_stops(
        self, year: int, included_event_ids: set[str], edges: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        selected = self._validate_coalition(year, included_event_ids)
        active_keys = set(
            zip(edges["sequence_id"], edges["from_order"].astype(int))
        ) | set(zip(edges["sequence_id"], edges["to_order"].astype(int)))
        key_frame = pd.DataFrame(sorted(active_keys), columns=["sequence_id", "stop_order"])
        stops = self.candidate_stops.merge(
            key_frame,
            on=["sequence_id", "stop_order"],
            how="inner",
            validate="one_to_one",
        )
        stops = gpd.GeoDataFrame(stops, geometry="geometry", crs=self.candidate_stops.crs)
        stops["year"] = year
        stops["passenger_service_active"] = True
        stops["station_status_rule"] = "active_with_incident_section"

        added_components = {
            component_id
            for package in selected
            for component_id in package.get("add_components", [])
        }
        removed_components = {
            component_id
            for package in selected
            for component_id in package.get("remove_components", [])
        }
        prior_snapshot = datetime.fromisoformat(
            f"{year - 1}-12-31T23:59:59+08:00"
        )
        for component_id, rule in self.station_rules.items():
            names = {normalized_name(value) for value in rule["station_names"]}
            mask = stops["sequence_id"].eq(rule["sequence_id"]) & stops[
                "normalized_name"
            ].isin(names)
            component = self.components[component_id]
            if rule["rule"] == "open_from_component_start":
                start = datetime.fromisoformat(component["service_start_cst"])
                is_open = start <= prior_snapshot or component_id in added_components
                if not is_open:
                    stops.loc[mask, "passenger_service_active"] = False
                    stops.loc[mask, "station_status_rule"] = "coalition_not_open"
            elif rule["rule"] == "closed_from_year":
                end = datetime.fromisoformat(component["service_end_cst"])
                is_closed = end <= prior_snapshot or component_id in removed_components
                if is_closed:
                    stops.loc[mask, "passenger_service_active"] = False
                    stops.loc[mask, "station_status_rule"] = "coalition_closed"
        return stops.sort_values(STOP_KEY).reset_index(drop=True)

    def connection_records(self, stops: gpd.GeoDataFrame) -> set[tuple]:
        active = stops.loc[stops["passenger_service_active"]]
        records: set[tuple] = set()
        for (_, first), (_, second) in itertools.combinations(active.iterrows(), 2):
            if first["sequence_id"] == second["sequence_id"]:
                continue
            exact = first["normalized_name"] == second["normalized_name"]
            aliases = self.alias_lookup.get(first["normalized_name"], set()) & self.alias_lookup.get(
                second["normalized_name"], set()
            )
            if not exact and not aliases:
                continue
            distance_m = float(
                GEOD.inv(first["lon"], first["lat"], second["lon"], second["lat"])[2]
            )
            threshold = self.topology["rules"][
                "same_name_connection_max_m"
                if exact
                else "explicit_alias_connection_max_m"
            ]
            if distance_m > threshold:
                continue
            endpoints = tuple(
                sorted(
                    [
                        (first["sequence_id"], int(first["stop_order"])),
                        (second["sequence_id"], int(second["stop_order"])),
                    ]
                )
            )
            same_route = first["route_identity"] == second["route_identity"]
            both_intercity = all(
                "_IC" in route
                for route in (first["route_identity"], second["route_identity"])
            )
            connection_class = (
                "same_route_pattern_continuity"
                if same_route
                else (
                    "intercity_junction_timetable_pending"
                    if both_intercity
                    else "passenger_transfer_candidate"
                )
            )
            records.add(
                endpoints
                + (
                    connection_class,
                    "exact" if exact else "explicit_alias",
                    ";".join(sorted(aliases)),
                )
            )
        return records

    def build(self, year: int, included_event_ids: set[str]) -> dict:
        edges = self.build_edges(year, included_event_ids)
        stops = self.build_stops(year, included_event_ids, edges)
        return {
            "edges": edges,
            "stops": stops,
            "connections": self.connection_records(stops),
        }
