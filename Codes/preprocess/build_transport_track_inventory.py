#!/usr/bin/env python3
"""Normalize the immutable OSM rail-track snapshot without inferring service."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("Data/raw/transport/osm/gba_passenger_rail_tracks_overpass_20260826.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("Data/interim/transport/osm_track_candidates.parquet"),
    )
    parser.add_argument(
        "--audit-json",
        type=Path,
        default=Path("Results/pilots/transport_track_inventory_audit.json"),
    )
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    rows: list[dict] = []
    invalid_geometry = 0
    for element in raw.get("elements", []):
        coordinates = [
            (float(node["lon"]), float(node["lat"]))
            for node in element.get("geometry", [])
            if "lon" in node and "lat" in node
        ]
        if len(coordinates) < 2:
            invalid_geometry += 1
            continue
        tags = element.get("tags") or {}
        rows.append(
            {
                "osm_type": clean(element.get("type")),
                "osm_id": int(element["id"]),
                "railway": clean(tags.get("railway")),
                "name": clean(tags.get("name")),
                "name_zh": clean(tags.get("name:zh")),
                "operator": clean(tags.get("operator")),
                "start_date": clean(tags.get("start_date")),
                "usage": clean(tags.get("usage")),
                "service": clean(tags.get("service")),
                "highspeed": clean(tags.get("highspeed")),
                "maxspeed": clean(tags.get("maxspeed")),
                "electrified": clean(tags.get("electrified")),
                "tracks": clean(tags.get("tracks")),
                "source_role": "present_geometry_candidate_only",
                "geometry": LineString(coordinates),
            }
        )

    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)

    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input),
        "input_sha256": sha256(args.input),
        "output": str(args.output),
        "source_role": "candidate present-day geometry; operating status requires verification",
        "n_raw_elements": len(raw.get("elements", [])),
        "n_rows_written": int(len(frame)),
        "n_invalid_geometry": int(invalid_geometry),
        "railway_counts": dict(Counter(frame["railway"].fillna("<missing>"))),
        "n_with_name": int(frame["name"].notna().sum()),
        "n_with_operator": int(frame["operator"].notna().sum()),
        "n_with_start_date": int(frame["start_date"].notna().sum()),
        "n_with_usage": int(frame["usage"].notna().sum()),
        "n_with_maxspeed": int(frame["maxspeed"].notna().sum()),
        "prohibition": "do not treat railway=rail as proof of passenger service or historical availability",
    }
    args.audit_json.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
