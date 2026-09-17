#!/usr/bin/env python3
"""Numerical core for rail-required potential accessibility."""

from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra


def rail_required_distance_matrix(
    n_stations: int,
    track_from: np.ndarray,
    track_to: np.ndarray,
    track_minutes: np.ndarray,
    transfer_from: np.ndarray,
    transfer_to: np.ndarray,
    transfer_minutes: np.ndarray,
) -> np.ndarray:
    """Shortest station times while requiring at least one directed track arc."""
    track_from = np.asarray(track_from, dtype=np.int64)
    track_to = np.asarray(track_to, dtype=np.int64)
    track_minutes = np.asarray(track_minutes, dtype=np.float64)
    transfer_from = np.asarray(transfer_from, dtype=np.int64)
    transfer_to = np.asarray(transfer_to, dtype=np.int64)
    transfer_minutes = np.asarray(transfer_minutes, dtype=np.float64)
    if np.any(track_minutes <= 0) or np.any(transfer_minutes < 0):
        raise ValueError("track weights must be positive and transfer weights nonnegative")
    # Layer 0 means no passenger-rail arc has yet been traversed; layer 1 means yes.
    rows = np.concatenate(
        [track_from, track_from + n_stations, transfer_from, transfer_from + n_stations]
    )
    columns = np.concatenate(
        [
            track_to + n_stations,
            track_to + n_stations,
            transfer_to,
            transfer_to + n_stations,
        ]
    )
    weights = np.concatenate(
        [track_minutes, track_minutes, transfer_minutes, transfer_minutes]
    )
    minimum_arc: dict[tuple[int, int], float] = {}
    for row, column, weight in zip(rows, columns, weights):
        key = (int(row), int(column))
        minimum_arc[key] = min(minimum_arc.get(key, np.inf), float(weight))
    arc_rows = np.fromiter((key[0] for key in minimum_arc), dtype=np.int64)
    arc_columns = np.fromiter((key[1] for key in minimum_arc), dtype=np.int64)
    arc_weights = np.fromiter(minimum_arc.values(), dtype=np.float64)
    graph = csr_matrix(
        (arc_weights, (arc_rows, arc_columns)),
        shape=(2 * n_stations, 2 * n_stations),
    )
    distances = dijkstra(
        graph, directed=True, indices=np.arange(n_stations), return_predecessors=False
    )[:, n_stations:]
    # A ride-away-and-back loop must not turn a same-occurrence walking opportunity
    # into rail-mediated accessibility.
    np.fill_diagonal(distances, np.inf)
    return distances


def origin_accessibility_metrics(
    rail_required_minutes: np.ndarray,
    boarding_station_indices: np.ndarray,
    boarding_walk_plus_wait_minutes: np.ndarray,
    egress_station_indices: np.ndarray,
    egress_destination_indices: np.ndarray,
    egress_walk_minutes: np.ndarray,
    destination_population: np.ndarray,
    destination_city_codes: np.ndarray,
    origin_city_code: int,
    maximum_time_min: float = 120.0,
    half_life_min: float = 30.0,
) -> tuple[float, float, float]:
    """Return total opportunity, cross-city opportunity and coverage."""
    boarding_station_indices = np.asarray(boarding_station_indices, dtype=np.int64)
    boarding_cost = np.asarray(
        boarding_walk_plus_wait_minutes, dtype=np.float64
    )
    coverage = float(len(boarding_station_indices) > 0)
    if not coverage or len(egress_station_indices) == 0:
        return 0.0, 0.0, coverage
    unique_boarding = np.unique(boarding_station_indices)
    minimum_boarding_cost = np.full(len(unique_boarding), np.inf)
    boarding_position = np.searchsorted(unique_boarding, boarding_station_indices)
    np.minimum.at(minimum_boarding_cost, boarding_position, boarding_cost)
    arrival_at_station = np.min(
        rail_required_minutes[unique_boarding]
        + minimum_boarding_cost[:, None],
        axis=0,
    )
    n_destinations = len(destination_population)
    destination_time = np.full(n_destinations, np.inf)
    candidate = (
        arrival_at_station[np.asarray(egress_station_indices, dtype=np.int64)]
        + np.asarray(egress_walk_minutes, dtype=np.float64)
    )
    np.minimum.at(
        destination_time,
        np.asarray(egress_destination_indices, dtype=np.int64),
        candidate,
    )
    valid = np.isfinite(destination_time) & (destination_time <= maximum_time_min)
    if not valid.any():
        return 0.0, 0.0, coverage
    decay = np.exp(-np.log(2.0) * destination_time[valid] / half_life_min)
    effective = np.asarray(destination_population, dtype=np.float64)[valid] * decay
    total = float(effective.sum())
    cross = float(
        effective[
            np.asarray(destination_city_codes, dtype=np.int64)[valid]
            != int(origin_city_code)
        ].sum()
    )
    return total, cross, coverage
