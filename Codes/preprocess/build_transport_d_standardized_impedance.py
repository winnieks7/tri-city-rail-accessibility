#!/usr/bin/env python3
"""Build outcome-blind fixed-service impedance tables for the D rail topology."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "Codes/config/transport_standardized_impedance.json"
TRACK_IN = ROOT / "Data/interim/transport/d_annual_active_track_edges.parquet"
CONNECTION_IN = ROOT / "Data/interim/transport/d_annual_station_connection_pairs.parquet"
TRACK_OUT = ROOT / "Data/interim/transport/d_standardized_track_edge_impedance.parquet"
BOARDING_OUT = ROOT / "Data/interim/transport/d_standardized_route_year_boarding.parquet"
CONNECTION_OUT = ROOT / "Data/interim/transport/d_standardized_directional_connections.parquet"
METADATA_OUT = ROOT / "Data/metadata/transport/d_standardized_impedance.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def edge_minutes(length_m: pd.Series, speed_kmh: pd.Series) -> pd.Series:
    return length_m / (speed_kmh * 1000.0 / 60.0)


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    route_modes = cfg["route_modes"]
    reference = cfg["reference"]
    conservative = cfg["conservative_r2"]

    edges = pd.read_parquet(TRACK_IN).drop(columns=["geometry"])
    edges["mode"] = edges["route_identity"].map(route_modes)
    for label, params in (("r0", reference), ("r2", conservative)):
        edges[f"{label}_speed_kmh"] = edges["mode"].map(
            {mode: values["speed_kmh"] for mode, values in params["mode_parameters"].items()}
        )
        edges[f"{label}_in_vehicle_min"] = edge_minutes(
            edges["track_length_m"], edges[f"{label}_speed_kmh"]
        )
    edge_columns = [
        "year", "sequence_id", "route_identity", "component_id", "from_order",
        "to_order", "from_station", "to_station", "track_length_m", "mode",
        "r0_speed_kmh", "r0_in_vehicle_min", "r2_speed_kmh", "r2_in_vehicle_min",
    ]
    edges = edges[edge_columns].sort_values(
        ["year", "sequence_id", "from_order", "to_order"]
    ).reset_index(drop=True)

    boarding = edges[["year", "route_identity", "mode"]].drop_duplicates()
    for label, params in (("r0", reference), ("r2", conservative)):
        boarding[f"{label}_standard_headway_min"] = boarding["mode"].map(
            {mode: values["standard_headway_min"] for mode, values in params["mode_parameters"].items()}
        )
        boarding[f"{label}_expected_initial_wait_min"] = boarding["mode"].map(
            {mode: values["expected_initial_wait_min"] for mode, values in params["mode_parameters"].items()}
        )
    boarding = boarding.sort_values(["year", "route_identity"]).reset_index(drop=True)

    connections = pd.read_parquet(CONNECTION_IN).drop(columns=["geometry"])
    directional_rows: list[dict] = []
    class_mapping = cfg["connection_class_mapping"]
    for row in connections.to_dict(orient="records"):
        for reverse in (False, True):
            if reverse:
                from_route = row["to_route_identity"]
                to_route = row["from_route_identity"]
                from_sequence = row["to_sequence_id"]
                to_sequence = row["from_sequence_id"]
                from_order = row["to_stop_order"]
                to_order = row["from_stop_order"]
                from_station = row["to_station"]
                to_station = row["from_station"]
            else:
                from_route = row["from_route_identity"]
                to_route = row["to_route_identity"]
                from_sequence = row["from_sequence_id"]
                to_sequence = row["to_sequence_id"]
                from_order = row["from_stop_order"]
                to_order = row["to_stop_order"]
                from_station = row["from_station"]
                to_station = row["to_station"]
            policy = class_mapping[row["connection_class"]]
            values = {
                "year": row["year"],
                "connection_pair_id": row["connection_pair_id"],
                "direction": "reverse" if reverse else "forward",
                "from_sequence_id": from_sequence,
                "from_stop_order": from_order,
                "from_route_identity": from_route,
                "from_station": from_station,
                "to_sequence_id": to_sequence,
                "to_stop_order": to_order,
                "to_route_identity": to_route,
                "to_station": to_station,
                "from_mode": route_modes[from_route],
                "to_mode": route_modes[to_route],
                "connection_class": row["connection_class"],
                "standardized_policy": policy,
                "transfer_stratum": row["transfer_stratum"],
            }
            for label, params in (("r0", reference), ("r2", conservative)):
                if policy == "directional_transfer_with_receiving_mode_wait":
                    walk = params["transfer_walk_min"][row["transfer_stratum"]]
                    wait = params["mode_parameters"][route_modes[to_route]][
                        "expected_initial_wait_min"
                    ]
                    total = walk + wait
                elif policy == "zero_penalty_continuity":
                    walk = 0.0
                    wait = 0.0
                    total = params["same_route_pattern_continuity_min"]
                else:
                    walk = 0.0
                    wait = 0.0
                    total = params[
                        "officially_verified_intercity_through_running_junction_min"
                    ]
                values[f"{label}_walk_min"] = walk
                values[f"{label}_receiving_wait_min"] = wait
                values[f"{label}_connection_min"] = total
            directional_rows.append(values)
    directional = pd.DataFrame(directional_rows).sort_values(
        ["year", "connection_pair_id", "direction"]
    ).reset_index(drop=True)

    for path in (TRACK_OUT, BOARDING_OUT, CONNECTION_OUT, METADATA_OUT):
        path.parent.mkdir(parents=True, exist_ok=True)
    edges.to_parquet(TRACK_OUT, index=False)
    boarding.to_parquet(BOARDING_OUT, index=False)
    directional.to_parquet(CONNECTION_OUT, index=False)

    metadata = {
        "version": cfg["version"],
        "outcome_data_read": False,
        "historical_timetable_values_used": False,
        "input_sha256": {
            str(CONFIG.relative_to(ROOT)): sha256(CONFIG),
            str(TRACK_IN.relative_to(ROOT)): sha256(TRACK_IN),
            str(CONNECTION_IN.relative_to(ROOT)): sha256(CONNECTION_IN),
        },
        "outputs": {
            str(TRACK_OUT.relative_to(ROOT)): {"rows": len(edges), "sha256": sha256(TRACK_OUT)},
            str(BOARDING_OUT.relative_to(ROOT)): {"rows": len(boarding), "sha256": sha256(BOARDING_OUT)},
            str(CONNECTION_OUT.relative_to(ROOT)): {"rows": len(directional), "sha256": sha256(CONNECTION_OUT)},
        },
    }
    METADATA_OUT.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
