#!/usr/bin/env python3
"""Archive the pre-closure 2024 Haizhu Tram route relation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUERY = ROOT / "Codes/download/overpass_hz1_20241101_route_members.query"
RAW = ROOT / "Data/raw/transport/osm/hz1_route_members_20241101_overpass_20260826.json"
METADATA = ROOT / "Data/metadata/transport/osm_hz1_route_members_20241101_20260826.json"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
EXPECTED = [
    "广州塔", "广州塔东", "猎德大桥南", "琶醍", "南风", "会展西",
    "会展中", "会展东", "琶洲大桥南", "琶洲塔", "万胜围",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    index = {(item["type"], int(item["id"])): item for item in payload["elements"]}
    relation = index.get(("relation", 7420348))
    if relation is None:
        raise RuntimeError("Historical HZ1 relation missing")
    names = []
    for member in relation.get("members", []):
        if not str(member.get("role", "")).startswith("stop"):
            continue
        item = index.get((member["type"], int(member["ref"])), {})
        name = (item.get("tags") or {}).get("name")
        if name and (not names or name != names[-1]):
            names.append(name)
    if names != EXPECTED:
        raise RuntimeError(f"Unexpected historical stop sequence: {names}")
    return {"element_count": len(payload["elements"]), "historical_stop_sequence": names}


def main() -> None:
    RAW.parent.mkdir(parents=True, exist_ok=True)
    METADATA.parent.mkdir(parents=True, exist_ok=True)
    query_text = " ".join(QUERY.read_text(encoding="utf-8").split())
    if RAW.exists():
        summary = validate(RAW)
        endpoint = "immutable_existing_snapshot"
    else:
        partial = RAW.with_suffix(RAW.suffix + ".part")
        endpoint = ""
        failures: list[str] = []
        summary = {}
        for candidate in ENDPOINTS:
            if partial.exists():
                partial.unlink()
            completed = subprocess.run(
                [
                    "curl", "--http1.1", "--fail", "--location", "--silent",
                    "--show-error", "--retry", "2", "--retry-all-errors",
                    "--connect-timeout", "30", "--max-time", "300",
                    "--data-urlencode", f"data={query_text}", "--output", str(partial),
                    candidate,
                ],
                cwd=ROOT,
                check=False,
            )
            if completed.returncode != 0:
                failures.append(f"{candidate}: curl exit {completed.returncode}")
                continue
            try:
                summary = validate(partial)
            except (json.JSONDecodeError, RuntimeError) as exc:
                failures.append(f"{candidate}: {exc}")
                continue
            endpoint = candidate
            os.replace(partial, RAW)
            break
        if not endpoint:
            raise RuntimeError("; ".join(failures))

    record = {
        "dataset": "OpenStreetMap historical Haizhu Tram HZ1 route relation",
        "historical_timestamp_utc": "2024-11-01T00:00:00Z",
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "query_file": str(QUERY.relative_to(ROOT)),
        "query_sha256": sha256(QUERY),
        "raw_file": str(RAW.relative_to(ROOT)),
        "raw_sha256": sha256(RAW),
        **summary,
        "license": "ODbL 1.0; OpenStreetMap contributors",
        "analytical_role": "pre-closure station coordinates and route order candidate",
        "official_override": "municipal closure record controls 2024-11-13 passenger-stop removal",
        "outcome_data_read": False,
    }
    METADATA.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
