#!/usr/bin/env python3
"""Independently validate frozen D rail path and generalized-time calculations."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Codes.analysis.transport_accessibility import rail_required_distance_matrix  # noqa: E402
from Codes.analysis.transport_d_network_assembler import DNetworkAssembler  # noqa: E402
from Codes.analysis.transport_event_state import FrozenEventStateBuilder  # noqa: E402


CONFIG = ROOT / "Codes/config/transport_d_independent_path_validation.json"
ORIGIN_WALK = ROOT / "Data/interim/transport/d_pedestrian_origin_station_walk.parquet"
DESTINATION_WALK = ROOT / "Data/interim/transport/d_pedestrian_station_destination_walk.parquet"
STATION_TABLE = ROOT / "Results/tables/transport_d_independent_station_path_validation.csv"
OD_TABLE = ROOT / "Results/tables/transport_d_independent_od_time_validation.csv"
AUDIT = ROOT / "Results/pilots/transport_d_independent_path_validation_audit.json"
REPORT = ROOT / "Results/TRANSPORT_D_INDEPENDENT_PATH_VALIDATION.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_station_indices(frame: pd.DataFrame, assembler: DNetworkAssembler) -> pd.DataFrame:
    output = frame.copy()
    output["station_index"] = [
        assembler.station_lookup[
            (row.sequence_id, row.route_identity, int(row.stop_order))
        ]
        for row in output.itertuples(index=False)
    ]
    return output


def add_min_edge(graph: nx.DiGraph, source: int, target: int, minutes: float) -> None:
    existing = graph.get_edge_data(source, target)
    if existing is None or minutes < existing["weight"]:
        graph.add_edge(source, target, weight=float(minutes))


def independent_layered_graph(n: int, network) -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_nodes_from(range(2 * n))
    for source, target, minutes in zip(
        network.track_from, network.track_to, network.track_minutes
    ):
        add_min_edge(graph, int(source), int(target) + n, float(minutes))
        add_min_edge(graph, int(source) + n, int(target) + n, float(minutes))
    for source, target, minutes in zip(
        network.transfer_from, network.transfer_to, network.transfer_minutes
    ):
        add_min_edge(graph, int(source), int(target), float(minutes))
        add_min_edge(graph, int(source) + n, int(target) + n, float(minutes))
    return graph


def state_sequence(builder: FrozenEventStateBuilder) -> list[tuple[int, int, set[str], str]]:
    states = [(2017, 2018, set(), "baseline_empty_2018")]
    for year in range(2018, 2025):
        events = {item["event_id"] for item in builder.packages_by_year[year]}
        states.append((year, year, events, "full_year_end"))
    return states


def station_label(assembler: DNetworkAssembler, index: int) -> str:
    row = assembler.stations.iloc[index]
    return f"{row.sequence_id}|{row.route_identity}|{int(row.stop_order)}"


def path_signature(path: list[int], assembler: DNetworkAssembler) -> str:
    n = len(assembler.stations)
    return ">".join(
        f"{station_label(assembler, node % n)}@{'rail_used' if node >= n else 'pre_rail'}"
        for node in path
    )


def sample_station_pairs(
    active: np.ndarray, count: int, seed: int, year: int
) -> list[tuple[int, int]]:
    active = np.unique(active.astype(np.int64))
    maximum = len(active) * (len(active) - 1)
    if maximum < count:
        raise RuntimeError(f"not enough active station pairs in {year}")
    mixed_seed = int.from_bytes(
        hashlib.sha256(f"{seed}|station|{year}".encode()).digest()[:8], "big"
    )
    rng = np.random.default_rng(mixed_seed)
    selected: set[tuple[int, int]] = set()
    while len(selected) < count:
        source, target = rng.choice(active, size=2, replace=False)
        selected.add((int(source), int(target)))
    return sorted(selected)


def hashed_od_pairs(
    origin_ids: list[str], destination_ids: list[str], count: int, seed: int, year: int
) -> list[tuple[str, str]]:
    if len(origin_ids) < count or not destination_ids:
        raise RuntimeError(f"insufficient active OD candidates in {year}")
    ranked_origins = sorted(
        origin_ids,
        key=lambda value: hashlib.sha256(
            f"{seed}|origin|{year}|{value}".encode()
        ).hexdigest(),
    )[:count]
    destinations = sorted(destination_ids)
    pairs = []
    for origin in ranked_origins:
        digest = hashlib.sha256(
            f"{seed}|destination|{year}|{origin}".encode()
        ).digest()
        index = int.from_bytes(digest[:8], "big") % len(destinations)
        pairs.append((origin, destinations[index]))
    return pairs


def finite_equal(first: float, second: float) -> bool:
    return bool(np.isfinite(first) == np.isfinite(second))


def value_error(first: float, second: float) -> float:
    if np.isinf(first) and np.isinf(second):
        return 0.0
    if not finite_equal(first, second):
        return np.inf
    return float(first - second)


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    tolerance = float(cfg["comparison"]["absolute_tolerance_min"])
    builder = FrozenEventStateBuilder()
    assembler = DNetworkAssembler()
    n = len(assembler.stations)
    origin_walk = add_station_indices(pd.read_parquet(ORIGIN_WALK), assembler)
    destination_walk = add_station_indices(pd.read_parquet(DESTINATION_WALK), assembler)
    station_rows: list[dict] = []
    od_rows: list[dict] = []

    for outcome_year, assembly_year, events, state_label in state_sequence(builder):
        state = builder.build(assembly_year, events)
        network = assembler.assemble(assembly_year, state, cfg["variant"])
        primary = rail_required_distance_matrix(
            n,
            network.track_from,
            network.track_to,
            network.track_minutes,
            network.transfer_from,
            network.transfer_to,
            network.transfer_minutes,
        )
        graph = independent_layered_graph(n, network)
        active = np.unique(network.active_station_indices)
        distance_cache: dict[int, dict[int, float]] = {}

        station_pairs = sample_station_pairs(
            active,
            int(cfg["station_pairs_per_state"]),
            int(cfg["sampling"]["seed"]),
            outcome_year,
        )
        for source, target in station_pairs:
            if source not in distance_cache:
                distance_cache[source] = nx.single_source_dijkstra_path_length(
                    graph, source, weight="weight"
                )
            independent = float(distance_cache[source].get(target + n, np.inf))
            primary_value = float(primary[source, target])
            error = value_error(primary_value, independent)
            path = (
                nx.shortest_path(graph, source, target + n, weight="weight")
                if np.isfinite(independent)
                else []
            )
            station_rows.append(
                {
                    "outcome_year": outcome_year,
                    "assembly_year": assembly_year,
                    "state": state_label,
                    "source_station_index": source,
                    "target_station_index": target,
                    "source_station": station_label(assembler, source),
                    "target_station": station_label(assembler, target),
                    "primary_scipy_minutes": primary_value,
                    "independent_networkx_minutes": independent,
                    "finite_status_agrees": finite_equal(primary_value, independent),
                    "difference_minutes": error,
                    "absolute_difference_minutes": abs(error),
                    "independent_path": path_signature(path, assembler) if path else "",
                }
            )

        active_set = set(active.tolist())
        active_origin = origin_walk.loc[origin_walk["station_index"].isin(active_set)]
        active_destination = destination_walk.loc[
            destination_walk["station_index"].isin(active_set)
        ]
        pairs = hashed_od_pairs(
            active_origin["grid_id"].drop_duplicates().tolist(),
            active_destination["pixel_id"].drop_duplicates().tolist(),
            int(cfg["origin_destination_pairs_per_state"]),
            int(cfg["sampling"]["seed"]),
            outcome_year,
        )
        for grid_id, pixel_id in pairs:
            boarding = active_origin.loc[active_origin["grid_id"].eq(grid_id)].copy()
            boarding["boarding_cost"] = boarding["walk_min"] + boarding[
                "route_identity"
            ].map(network.boarding_wait_by_route)
            if boarding["boarding_cost"].isna().any():
                raise RuntimeError(f"missing wait for validation origin {grid_id}")
            egress = active_destination.loc[
                active_destination["pixel_id"].eq(pixel_id)
            ].copy()
            primary_best = (np.inf, None, None)
            independent_best = (np.inf, None, None, [])
            for board in boarding.itertuples(index=False):
                source = int(board.station_index)
                if source not in distance_cache:
                    distance_cache[source] = nx.single_source_dijkstra_path_length(
                        graph, source, weight="weight"
                    )
                for exit_record in egress.itertuples(index=False):
                    target = int(exit_record.station_index)
                    if source == target:
                        continue
                    primary_candidate = (
                        float(board.boarding_cost)
                        + float(primary[source, target])
                        + float(exit_record.walk_min)
                    )
                    if primary_candidate < primary_best[0]:
                        primary_best = (primary_candidate, source, target)
                    nx_rail = float(distance_cache[source].get(target + n, np.inf))
                    independent_candidate = (
                        float(board.boarding_cost)
                        + nx_rail
                        + float(exit_record.walk_min)
                    )
                    if independent_candidate < independent_best[0]:
                        path = (
                            nx.shortest_path(
                                graph, source, target + n, weight="weight"
                            )
                            if np.isfinite(nx_rail)
                            else []
                        )
                        independent_best = (
                            independent_candidate,
                            source,
                            target,
                            path,
                        )
            error = value_error(primary_best[0], independent_best[0])
            od_rows.append(
                {
                    "outcome_year": outcome_year,
                    "assembly_year": assembly_year,
                    "state": state_label,
                    "grid_id": grid_id,
                    "pixel_id": pixel_id,
                    "primary_scipy_generalized_minutes": primary_best[0],
                    "independent_networkx_generalized_minutes": independent_best[0],
                    "finite_status_agrees": finite_equal(
                        primary_best[0], independent_best[0]
                    ),
                    "difference_minutes": error,
                    "absolute_difference_minutes": abs(error),
                    "primary_board_station_index": primary_best[1],
                    "primary_egress_station_index": primary_best[2],
                    "independent_board_station_index": independent_best[1],
                    "independent_egress_station_index": independent_best[2],
                    "independent_path": path_signature(independent_best[3], assembler)
                    if independent_best[3]
                    else "",
                }
            )

    station_table = pd.DataFrame(station_rows)
    od_table = pd.DataFrame(od_rows)
    finite_station = station_table["absolute_difference_minutes"].replace(
        [np.inf, -np.inf], np.nan
    )
    finite_od = od_table["absolute_difference_minutes"].replace(
        [np.inf, -np.inf], np.nan
    )
    checks = {
        "expected_state_count": station_table["outcome_year"].nunique() == 8,
        "expected_station_pair_count": len(station_table)
        == 8 * int(cfg["station_pairs_per_state"]),
        "expected_od_pair_count": len(od_table)
        == 8 * int(cfg["origin_destination_pairs_per_state"]),
        "station_finite_status_all_agree": bool(
            station_table["finite_status_agrees"].all()
        ),
        "od_finite_status_all_agree": bool(od_table["finite_status_agrees"].all()),
        "station_values_within_tolerance": float(finite_station.max()) <= tolerance,
        "od_values_within_tolerance": float(finite_od.max()) <= tolerance,
    }
    audit = {
        "analysis": "transport_D_independent_path_and_time_validation",
        "validation_role": "post-outcome numerical implementation diagnostic",
        "interpretation_boundary": cfg["interpretation"],
        "config": str(CONFIG.relative_to(ROOT)),
        "config_sha256": sha256(CONFIG),
        "inputs": {
            str(ORIGIN_WALK.relative_to(ROOT)): sha256(ORIGIN_WALK),
            str(DESTINATION_WALK.relative_to(ROOT)): sha256(DESTINATION_WALK),
        },
        "counts": {
            "states": int(station_table["outcome_year"].nunique()),
            "station_pairs": len(station_table),
            "od_pairs": len(od_table),
            "finite_station_pairs": int(
                np.isfinite(station_table["primary_scipy_minutes"]).sum()
            ),
            "finite_od_pairs": int(
                np.isfinite(od_table["primary_scipy_generalized_minutes"]).sum()
            ),
        },
        "maximum_absolute_difference_minutes": {
            "station_path": float(finite_station.max()),
            "origin_destination_generalized_time": float(finite_od.max()),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    if not audit["passed"]:
        raise RuntimeError(json.dumps(audit, ensure_ascii=False, indent=2))
    STATION_TABLE.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    station_table.to_csv(STATION_TABLE, index=False)
    od_table.to_csv(OD_TABLE, index=False)
    audit["outputs"] = {
        str(STATION_TABLE.relative_to(ROOT)): {
            "rows": len(station_table),
            "sha256": sha256(STATION_TABLE),
        },
        str(OD_TABLE.relative_to(ROOT)): {
            "rows": len(od_table),
            "sha256": sha256(OD_TABLE),
        },
    }
    AUDIT.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    REPORT.write_text(
        "\n".join(
            [
                "# D组独立路径与广义时间核验",
                "",
                "主实现使用 SciPy 稀疏图最短路；核验实现独立构建 NetworkX 双层有向图，并对固定、结果无关的样本逐条比较。双层图要求至少经过一条客运轨道边，同一站点发生的乘出再返回路径被排除。",
                "",
                f"- 状态：{audit['counts']['states']}（2017基线和2018—2024年末完整网络）",
                f"- 站点发生对：{audit['counts']['station_pairs']}，其中有限路径 {audit['counts']['finite_station_pairs']}",
                f"- 起点—目的地对：{audit['counts']['od_pairs']}，其中有限路径 {audit['counts']['finite_od_pairs']}",
                f"- 站点路径最大绝对差：{audit['maximum_absolute_difference_minutes']['station_path']:.3e} 分钟",
                f"- 广义时间最大绝对差：{audit['maximum_absolute_difference_minutes']['origin_destination_generalized_time']:.3e} 分钟",
                f"- 审计：{'PASS' if audit['passed'] else 'FAIL'}",
                "",
                "该核验只支持数值实现一致性；它不验证历史班次、标准化服务参数或真实出行时间。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
