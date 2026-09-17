#!/usr/bin/env python3
"""Assign native WorldPop pixels to cities and allocate origin population weights."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import Window
from shapely import area, intersection
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "Codes/config/transport_worldpop_2023.json"
BOUNDARIES = ROOT / "Data/interim/aoi/gba_city_boundaries.geojson"
GRID = ROOT / "Data/processed/transport/transport_grid_500m.parquet"
DEST_OUT = ROOT / "Data/processed/transport/worldpop_2023_destination_pixels.parquet"
ORIGIN_OUT = ROOT / "Data/processed/transport/worldpop_2023_origin_weights_500m.parquet"
METADATA_OUT = ROOT / "Data/metadata/transport/transport_worldpop_2023.json"
LAEA = "+proj=laea +lat_0=22.8 +lon_0=113.5 +datum=WGS84 +units=m +no_defs"
NINE = [
    "Guangzhou", "Foshan", "Dongguan", "Shenzhen", "Huizhou",
    "Zhuhai", "Zhongshan", "Jiangmen", "Zhaoqing",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    source_path = ROOT / cfg["source"]["path"]
    if sha256(source_path) != cfg["source"]["sha256"]:
        raise RuntimeError("WorldPop source hash mismatch")

    cities_wgs = gpd.read_file(BOUNDARIES)
    cities_wgs = cities_wgs[cities_wgs["gba_city"].isin(NINE)][
        ["gba_city", "geometry"]
    ].copy()
    city_order = {city: index for index, city in enumerate(NINE)}
    minx, miny, maxx, maxy = cities_wgs.total_bounds

    records = []
    with rasterio.open(source_path) as source:
        window = source.window(minx, miny, maxx, maxy).round_offsets().round_lengths()
        window = window.intersection(Window(0, 0, source.width, source.height))
        values = source.read(1, window=window)
        transform = source.window_transform(window)
        valid_rows, valid_cols = np.nonzero(
            np.isfinite(values) & (values != source.nodata) & (values > 0)
        )
        for row, col in zip(valid_rows.tolist(), valid_cols.tolist()):
            global_row = int(window.row_off) + row
            global_col = int(window.col_off) + col
            left, top = transform * (col, row)
            right, bottom = transform * (col + 1, row + 1)
            records.append(
                {
                    "pixel_id": f"wp2023_r{global_row:05d}_c{global_col:05d}",
                    "raster_row": global_row,
                    "raster_col": global_col,
                    "population": float(values[row, col]),
                    "centroid_lon": (left + right) / 2,
                    "centroid_lat": (bottom + top) / 2,
                    "geometry": box(left, bottom, right, top),
                }
            )
    pixels_wgs = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
    intersections = gpd.sjoin(
        pixels_wgs[["pixel_id", "geometry"]],
        cities_wgs,
        predicate="intersects",
        how="inner",
    )[["pixel_id", "gba_city"]].drop_duplicates()
    intersecting_ids = set(intersections["pixel_id"])
    pixels_wgs = pixels_wgs[pixels_wgs["pixel_id"].isin(intersecting_ids)].copy()

    centroid_points = pixels_wgs.copy()
    centroid_points["geometry"] = gpd.points_from_xy(
        centroid_points["centroid_lon"], centroid_points["centroid_lat"], crs="EPSG:4326"
    )
    contained = gpd.sjoin(
        centroid_points[["pixel_id", "geometry"]],
        cities_wgs,
        predicate="within",
        how="left",
    )[["pixel_id", "gba_city"]].dropna()
    contained = contained.sort_values(
        ["pixel_id", "gba_city"],
        key=lambda column: column.map(city_order) if column.name == "gba_city" else column,
    ).drop_duplicates("pixel_id")
    assignment = dict(zip(contained["pixel_id"], contained["gba_city"]))

    pixels_laea = pixels_wgs.to_crs(LAEA)
    cities_laea = cities_wgs.to_crs(LAEA)
    city_geometry = dict(zip(cities_laea["gba_city"], cities_laea.geometry))
    fallback_ids = [pixel_id for pixel_id in pixels_laea["pixel_id"] if pixel_id not in assignment]
    candidate_cities = intersections.groupby("pixel_id")["gba_city"].apply(list).to_dict()
    pixel_geometry = dict(zip(pixels_laea["pixel_id"], pixels_laea.geometry))
    for pixel_id in fallback_ids:
        scored = [
            (
                float(pixel_geometry[pixel_id].intersection(city_geometry[city]).area),
                -city_order[city],
                city,
            )
            for city in candidate_cities[pixel_id]
        ]
        assignment[pixel_id] = max(scored)[2]
    pixels_laea["assigned_city"] = pixels_laea["pixel_id"].map(assignment)
    if pixels_laea["assigned_city"].isna().any():
        raise RuntimeError("an intersecting positive WorldPop pixel was not assigned")
    pixels_laea["native_pixel_area_m2"] = pixels_laea.geometry.area
    destination = pixels_laea.drop(columns="geometry").merge(
        centroid_points[["pixel_id", "geometry"]].to_crs(LAEA),
        on="pixel_id",
        validate="one_to_one",
    )
    destination = gpd.GeoDataFrame(destination, geometry="geometry", crs=LAEA)
    destination = destination.sort_values("pixel_id").reset_index(drop=True)

    grid = gpd.read_parquet(GRID)
    eligible = grid[
        grid["analysis_eligible"] & grid["gba_city"].isin(NINE)
    ][["grid_id", "gba_city", "split_group", "geometry"]].copy()
    pairs = gpd.sjoin(
        pixels_laea[["pixel_id", "population", "native_pixel_area_m2", "geometry"]],
        eligible,
        predicate="intersects",
        how="inner",
    )
    grid_geometries = eligible.geometry.rename("grid_geometry")
    pairs = pairs.join(grid_geometries, on="index_right")
    overlap_area = area(intersection(pairs.geometry.values, pairs["grid_geometry"].values))
    pairs["allocated_population"] = (
        pairs["population"].to_numpy()
        * overlap_area
        / pairs["native_pixel_area_m2"].to_numpy()
    )
    origin = (
        pairs.groupby(["grid_id", "gba_city", "split_group"], as_index=False)[
            "allocated_population"
        ]
        .sum()
        .rename(columns={"gba_city": "city", "allocated_population": "population_weight"})
    )
    all_eligible = eligible.drop(columns="geometry").rename(columns={"gba_city": "city"})
    origin = all_eligible.merge(
        origin,
        on=["grid_id", "city", "split_group"],
        how="left",
        validate="one_to_one",
    )
    origin["population_weight"] = origin["population_weight"].fillna(0.0)

    DEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    destination.to_parquet(DEST_OUT, index=False)
    origin.sort_values("grid_id").to_parquet(ORIGIN_OUT, index=False)
    metadata = {
        "version": cfg["version"],
        "accessibility_outcome_read": False,
        "config_sha256": sha256(CONFIG),
        "source_sha256": sha256(source_path),
        "counts": {
            "positive_intersecting_destination_pixels": int(len(destination)),
            "eligible_origin_cells": int(len(origin)),
            "zero_population_origin_cells": int((origin["population_weight"] == 0).sum()),
        },
        "destination_population_by_city": {
            str(city): float(value)
            for city, value in destination.groupby("assigned_city")["population"].sum().items()
        },
        "origin_population_by_city": {
            str(city): float(value)
            for city, value in origin.groupby("city")["population_weight"].sum().items()
        },
        "outputs": {
            str(DEST_OUT.relative_to(ROOT)): {"sha256": sha256(DEST_OUT), "rows": len(destination)},
            str(ORIGIN_OUT.relative_to(ROOT)): {"sha256": sha256(ORIGIN_OUT), "rows": len(origin)},
        },
    }
    METADATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    METADATA_OUT.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
