#!/usr/bin/env python3
"""Normalize the immutable OSM GBA rail-station snapshot and audit date coverage.

OSM opening dates are retained as candidate metadata only. This script never
labels them as official ground truth. It writes a row-preserving GeoParquet and
machine-readable audit summaries for the transport data gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point


EXACT_DATE = re.compile(r"^(?P<year>18\d{2}|19\d{2}|20\d{2})(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def coordinate(element: dict) -> tuple[float | None, float | None]:
    if "lon" in element and "lat" in element:
        return float(element["lon"]), float(element["lat"])
    center = element.get("center") or {}
    if "lon" in center and "lat" in center:
        return float(center["lon"]), float(center["lat"])
    return None, None


def clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_year(value: str | None) -> tuple[int | None, bool]:
    if value is None:
        return None, False
    match = EXACT_DATE.fullmatch(value)
    if not match:
        return None, False
    return int(match.group("year")), True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("Data/raw/transport/osm/gba_rail_stations_overpass_20260826.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("Data/interim/transport/osm_station_candidates.parquet"),
    )
    parser.add_argument(
        "--audit-json",
        type=Path,
        default=Path("Results/pilots/transport_station_inventory_audit.json"),
    )
    parser.add_argument(
        "--operator-csv",
        type=Path,
        default=Path("Results/pilots/transport_station_date_coverage_by_operator.csv"),
    )
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    rows: list[dict] = []
    missing_coordinate = 0
    for element in raw.get("elements", []):
        lon, lat = coordinate(element)
        if lon is None or lat is None:
            missing_coordinate += 1
            continue
        tags = element.get("tags") or {}
        start_date = clean(tags.get("start_date"))
        opening_date = clean(tags.get("opening_date"))
        candidate_date = start_date or opening_date
        opening_year, exact_date_syntax = parse_year(candidate_date)
        rows.append(
            {
                "osm_type": clean(element.get("type")),
                "osm_id": int(element["id"]),
                "name": clean(tags.get("name")),
                "name_zh": clean(tags.get("name:zh")),
                "railway": clean(tags.get("railway")),
                "station": clean(tags.get("station")),
                "operator": clean(tags.get("operator")),
                "network": clean(tags.get("network")),
                "start_date": start_date,
                "opening_date": opening_date,
                "candidate_opening_date": candidate_date,
                "candidate_opening_year": opening_year,
                "candidate_date_exact_syntax": bool(exact_date_syntax),
                "source_role": "secondary_candidate_only",
                "lon": lon,
                "lat": lat,
                "geometry": Point(lon, lat),
            }
        )

    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    args.operator_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)

    coverage = (
        frame.assign(operator=frame["operator"].fillna("<missing>"))
        .groupby("operator", dropna=False)
        .agg(
            n_objects=("osm_id", "size"),
            n_with_candidate_date=("candidate_opening_date", lambda s: int(s.notna().sum())),
            n_with_exact_date_syntax=("candidate_date_exact_syntax", "sum"),
        )
        .reset_index()
    )
    coverage["candidate_date_fraction"] = (
        coverage["n_with_candidate_date"] / coverage["n_objects"]
    )
    coverage = coverage.sort_values(["n_objects", "operator"], ascending=[False, True])
    coverage.to_csv(args.operator_csv, index=False)

    invalid_dates = sorted(
        Counter(
            str(value)
            for value in frame.loc[
                frame["candidate_opening_date"].notna()
                & ~frame["candidate_date_exact_syntax"],
                "candidate_opening_date",
            ]
        ).items(),
        key=lambda item: (-item[1], item[0]),
    )
    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input),
        "input_sha256": sha256(args.input),
        "output": str(args.output),
        "source_role": "candidate geometry and secondary dates; not official truth",
        "n_raw_elements": len(raw.get("elements", [])),
        "n_rows_written": int(len(frame)),
        "n_missing_coordinate": int(missing_coordinate),
        "n_with_name": int(frame["name"].notna().sum()),
        "n_with_start_date": int(frame["start_date"].notna().sum()),
        "n_with_opening_date": int(frame["opening_date"].notna().sum()),
        "n_with_candidate_date": int(frame["candidate_opening_date"].notna().sum()),
        "n_with_exact_date_syntax": int(frame["candidate_date_exact_syntax"].sum()),
        "candidate_date_fraction": float(frame["candidate_opening_date"].notna().mean()),
        "candidate_date_exact_fraction": float(frame["candidate_date_exact_syntax"].mean()),
        "candidate_year_min": int(frame["candidate_opening_year"].dropna().min()),
        "candidate_year_max": int(frame["candidate_opening_year"].dropna().max()),
        "invalid_or_complex_date_counts": invalid_dates,
        "operator_summary_csv": str(args.operator_csv),
        "prohibition": "do not use OSM candidate dates as the sole evidence for key rail openings",
    }
    args.audit_json.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
