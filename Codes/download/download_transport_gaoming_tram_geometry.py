#!/usr/bin/env python3
"""Archive immutable OSM geometry for the suspended Gaoming tram."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
QUERY = ROOT / "Codes/download/overpass_gaoming_tram_geometry.query"
RAW = ROOT / "Data/raw/transport/osm/gaoming_tram_geometry_overpass_20260826.json"
METADATA = ROOT / "Data/metadata/transport/osm_gaoming_tram_geometry_20260826.json"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    elements = payload.get("elements") or []
    stop_names = sorted(
        {
            str((item.get("tags") or {}).get("name"))
            for item in elements
            if (item.get("tags") or {}).get("tram") == "yes"
            and (item.get("tags") or {}).get("name")
        }
    )
    track_ways = [
        item
        for item in elements
        if item.get("type") == "way"
        and (item.get("tags") or {}).get("railway") == "tram"
        and (item.get("tags") or {}).get("service") != "yard"
    ]
    expected = {
        "沧江路", "跃华路", "怡乐路", "荷城", "文化中心",
        "明湖公园", "新江路", "体育中心", "阮埇", "智湖",
    }
    if not expected <= set(stop_names):
        raise RuntimeError(f"Missing named stops: {sorted(expected - set(stop_names))}")
    if not track_ways:
        raise RuntimeError("No non-yard tram track ways returned")
    return {
        "element_count": len(elements),
        "named_stop_count": len(expected),
        "named_stops": sorted(expected),
        "non_yard_track_way_count": len(track_ways),
    }


def main() -> None:
    RAW.parent.mkdir(parents=True, exist_ok=True)
    METADATA.parent.mkdir(parents=True, exist_ok=True)
    query_text = " ".join(QUERY.read_text(encoding="utf-8").split())
    if RAW.exists():
        summary = validate(RAW)
        endpoint = "immutable_existing_snapshot"
    else:
        partial = RAW.with_suffix(RAW.suffix + ".part")
        failures: list[str] = []
        endpoint = ""
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
        "dataset": "OpenStreetMap Gaoming tram named stops and track geometry",
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "query_file": str(QUERY.relative_to(ROOT)),
        "query_sha256": sha256(QUERY),
        "raw_file": str(RAW.relative_to(ROOT)),
        "raw_sha256": sha256(RAW),
        **summary,
        "license": "ODbL 1.0; OpenStreetMap contributors",
        "analytical_role": "candidate coordinates and alignment; official station order and service dates override",
        "outcome_data_read": False,
    }
    METADATA.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
