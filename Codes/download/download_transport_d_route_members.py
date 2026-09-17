#!/usr/bin/env python3
"""Download an immutable OSM relation-member snapshot for the D network.

The snapshot is present-day candidate geometry only. Historical availability
must be reconstructed from the frozen official component table and endpoint
sequences; no OSM date is treated as official evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUERY = ROOT / "Codes/download/overpass_transport_d_route_members.query"
RAW = ROOT / "Data/raw/transport/osm/d_route_members_overpass_20260826.json"
METADATA = ROOT / "Data/metadata/transport/osm_d_route_members_20260826.json"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    elements = payload.get("elements")
    if not isinstance(elements, list) or not elements:
        raise RuntimeError("Overpass response has no elements")
    relations = [item for item in elements if item.get("type") == "relation"]
    if len(relations) < 25:
        raise RuntimeError(f"Only {len(relations)} requested relations were returned")
    return {
        "element_count": len(elements),
        "relation_count": len(relations),
        "relation_ids": sorted(int(item["id"]) for item in relations),
    }


def main() -> None:
    RAW.parent.mkdir(parents=True, exist_ok=True)
    METADATA.parent.mkdir(parents=True, exist_ok=True)
    if RAW.exists():
        if RAW.stat().st_size < 1024:
            raise RuntimeError(f"Immutable raw target is unexpectedly small: {RAW}")
        endpoint = "immutable_existing_snapshot"
        summary = validate(RAW)
    else:
        partial = RAW.with_suffix(RAW.suffix + ".part")
        errors: list[str] = []
        endpoint = ""
        summary = {}
        for candidate in ENDPOINTS:
            if partial.exists():
                partial.unlink()
            completed = subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--retry",
                    "2",
                    "--retry-all-errors",
                    "--connect-timeout",
                    "30",
                    "--max-time",
                    "900",
                    "--user-agent",
                    "Mozilla/5.0 CarbonAnalysis/transport-study",
                    "--data-binary",
                    f"@{QUERY}",
                    "--output",
                    str(partial),
                    candidate,
                ],
                cwd=ROOT,
                check=False,
            )
            if completed.returncode != 0:
                errors.append(f"{candidate}: curl exit {completed.returncode}")
                continue
            try:
                summary = validate(partial)
            except (json.JSONDecodeError, RuntimeError) as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            endpoint = candidate
            os.replace(partial, RAW)
            break
        if not endpoint:
            raise RuntimeError("; ".join(errors))

    record = {
        "dataset": "OpenStreetMap D-network selected route relations with recursive members",
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "query_file": str(QUERY.relative_to(ROOT)),
        "query_sha256": sha256(QUERY),
        "raw_file": str(RAW.relative_to(ROOT)),
        "raw_sha256": sha256(RAW),
        **summary,
        "license": "ODbL 1.0; OpenStreetMap contributors",
        "analytical_role": "present-day candidate geometry and stop order only",
        "prohibition": "do not back-project current relations; official component dates and endpoint trims control every annual snapshot",
        "outcome_data_read": False,
    }
    METADATA.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
