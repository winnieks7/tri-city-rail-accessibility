#!/usr/bin/env python3
"""Assemble weighted rail graphs for arbitrary frozen D event coalitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STOPS = ROOT / "Data/interim/transport/d_route_stop_sequence_candidates.parquet"
TRACK = ROOT / "Data/interim/transport/d_standardized_track_edge_impedance.parquet"
CONNECTIONS = ROOT / "Data/interim/transport/d_standardized_directional_connections.parquet"
BOARDING = ROOT / "Data/interim/transport/d_standardized_route_year_boarding.parquet"
STATION_KEY = ["sequence_id", "route_identity", "stop_order"]
TRACK_KEY = [
    "sequence_id", "route_identity", "component_id", "from_order", "to_order"
]


@dataclass
class AssembledNetwork:
    track_from: np.ndarray
    track_to: np.ndarray
    track_minutes: np.ndarray
    transfer_from: np.ndarray
    transfer_to: np.ndarray
    transfer_minutes: np.ndarray
    active_station_indices: np.ndarray
    boarding_wait_by_route: dict[str, float]
    diagnostics: dict


class DNetworkAssembler:
    def __init__(self) -> None:
        stops = pd.read_parquet(STOPS)[STATION_KEY].drop_duplicates()
        stops = stops.sort_values(STATION_KEY).reset_index(drop=True)
        stops.insert(0, "station_index", np.arange(len(stops), dtype=np.int64))
        self.stations = stops
        self.station_lookup = {
            (row.sequence_id, row.route_identity, int(row.stop_order)): int(
                row.station_index
            )
            for row in stops.itertuples(index=False)
        }
        self.sequence_route = (
            stops[["sequence_id", "route_identity"]]
            .drop_duplicates()
            .set_index("sequence_id")["route_identity"]
            .to_dict()
        )
        self.track = pd.read_parquet(TRACK)
        self.connections = pd.read_parquet(CONNECTIONS)
        self.boarding = pd.read_parquet(BOARDING)

    @staticmethod
    def endpoint_pair(
        first_sequence: str, first_order: int, second_sequence: str, second_order: int
    ) -> tuple:
        return tuple(
            sorted(
                [
                    (str(first_sequence), int(first_order)),
                    (str(second_sequence), int(second_order)),
                ]
            )
        )

    def assemble(self, year: int, state: dict, variant: str = "r0") -> AssembledNetwork:
        if variant not in {"r0", "r2"}:
            raise ValueError("only frozen r0 and r2 impedance variants are valid")
        track_weight = f"{variant}_in_vehicle_min"
        connection_weight = f"{variant}_connection_min"
        wait_weight = f"{variant}_expected_initial_wait_min"
        years = {year - 1, year}
        track_lookup = self.track.loc[self.track["year"].isin(years)].copy()
        track_lookup["prefer"] = track_lookup["year"].eq(year).astype(int)
        track_lookup = track_lookup.sort_values("prefer", ascending=False).drop_duplicates(
            TRACK_KEY
        )
        state_edges = state["edges"].merge(
            track_lookup[TRACK_KEY + [track_weight]],
            on=TRACK_KEY,
            how="left",
            validate="one_to_one",
        )
        if state_edges[track_weight].isna().any():
            raise RuntimeError(f"{year} coalition has an unweighted track edge")
        edge_from = np.array(
            [
                self.station_lookup[
                    (row.sequence_id, row.route_identity, int(row.from_order))
                ]
                for row in state_edges.itertuples(index=False)
            ],
            dtype=np.int64,
        )
        edge_to = np.array(
            [
                self.station_lookup[
                    (row.sequence_id, row.route_identity, int(row.to_order))
                ]
                for row in state_edges.itertuples(index=False)
            ],
            dtype=np.int64,
        )
        weights = state_edges[track_weight].to_numpy(dtype=np.float64)
        track_from = np.concatenate([edge_from, edge_to])
        track_to = np.concatenate([edge_to, edge_from])
        track_minutes = np.concatenate([weights, weights])

        active_connection_pairs = {
            (record[0], record[1]) for record in state["connections"]
        }
        connection_lookup = self.connections.loc[
            self.connections["year"].isin(years)
        ].copy()
        connection_lookup["endpoint_pair"] = [
            self.endpoint_pair(
                row.from_sequence_id,
                row.from_stop_order,
                row.to_sequence_id,
                row.to_stop_order,
            )
            for row in connection_lookup.itertuples(index=False)
        ]
        connection_lookup = connection_lookup.loc[
            connection_lookup["endpoint_pair"].isin(active_connection_pairs)
        ].copy()
        connection_lookup["prefer"] = connection_lookup["year"].eq(year).astype(int)
        directed_key = [
            "from_sequence_id", "from_stop_order", "to_sequence_id", "to_stop_order"
        ]
        connection_lookup = connection_lookup.sort_values(
            "prefer", ascending=False
        ).drop_duplicates(directed_key)
        observed_pairs = set(connection_lookup["endpoint_pair"])
        if observed_pairs != active_connection_pairs:
            missing = active_connection_pairs - observed_pairs
            raise RuntimeError(f"{year} coalition has unweighted connection pairs: {missing}")
        transfer_from = np.array(
            [
                self.station_lookup[
                    (
                        row.from_sequence_id,
                        row.from_route_identity,
                        int(row.from_stop_order),
                    )
                ]
                for row in connection_lookup.itertuples(index=False)
            ],
            dtype=np.int64,
        )
        transfer_to = np.array(
            [
                self.station_lookup[
                    (
                        row.to_sequence_id,
                        row.to_route_identity,
                        int(row.to_stop_order),
                    )
                ]
                for row in connection_lookup.itertuples(index=False)
            ],
            dtype=np.int64,
        )
        transfer_minutes = connection_lookup[connection_weight].to_numpy(
            dtype=np.float64
        )

        active_stops = state["stops"].loc[
            state["stops"]["passenger_service_active"]
        ]
        active_station_indices = np.array(
            [
                self.station_lookup[
                    (row.sequence_id, row.route_identity, int(row.stop_order))
                ]
                for row in active_stops.itertuples(index=False)
            ],
            dtype=np.int64,
        )
        active_routes = set(active_stops["route_identity"])
        boarding = self.boarding.loc[
            self.boarding["year"].isin(years)
            & self.boarding["route_identity"].isin(active_routes)
        ].copy()
        boarding["prefer"] = boarding["year"].eq(year).astype(int)
        boarding = boarding.sort_values("prefer", ascending=False).drop_duplicates(
            "route_identity"
        )
        boarding_wait = dict(zip(boarding["route_identity"], boarding[wait_weight]))
        if set(boarding_wait) != active_routes:
            raise RuntimeError(f"{year} coalition has an unweighted active route")
        diagnostics = {
            "undirected_track_edges": len(state_edges),
            "directed_track_arcs": len(track_from),
            "connection_pairs": len(active_connection_pairs),
            "directed_transfer_arcs": len(transfer_from),
            "active_station_occurrences": len(active_station_indices),
            "active_routes": len(active_routes),
        }
        return AssembledNetwork(
            track_from=track_from,
            track_to=track_to,
            track_minutes=track_minutes,
            transfer_from=transfer_from,
            transfer_to=transfer_to,
            transfer_minutes=transfer_minutes,
            active_station_indices=active_station_indices,
            boarding_wait_by_route=boarding_wait,
            diagnostics=diagnostics,
        )
