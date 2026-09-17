#!/usr/bin/env python3
"""Build the frozen nested 500 m/1 km transport grid and JRC water eligibility."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from pyproj import CRS
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from shapely import area, box, intersection
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "Codes/config/transport_study_contract.json"
BOUNDARY_PATH = ROOT / "Data/interim/aoi/gba_city_boundaries.geojson"
GSW_DIR = ROOT / "Data/raw/controls/jrc_gsw_v1_4_occurrence"
OUT_500 = ROOT / "Data/processed/transport/transport_grid_500m.parquet"
OUT_1000 = ROOT / "Data/processed/transport/transport_grid_1000m.parquet"
WATER_RASTER = ROOT / "Data/interim/transport/jrc_gsw_water_aoi_fraction_500m.tif"
METADATA = ROOT / "Data/metadata/transport/transport_analysis_grid.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def grid_indices(bounds: np.ndarray, cell: int) -> tuple[int, int, int, int]:
    minx, miny, maxx, maxy = bounds
    return (
        math.floor(minx / cell),
        math.ceil(maxx / cell) - 1,
        math.floor(miny / cell),
        math.ceil(maxy / cell) - 1,
    )


def city_overlaps(
    geometries: np.ndarray,
    ix: np.ndarray,
    iy: np.ndarray,
    cities: gpd.GeoDataFrame,
    cell: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    total = np.zeros(len(geometries), dtype="float64")
    best = np.zeros(len(geometries), dtype="float64")
    city_name = np.full(len(geometries), "", dtype=object)
    for row in cities.itertuples():
        geom = row.geometry
        minx, miny, maxx, maxy = geom.bounds
        candidate = np.flatnonzero(
            (ix * cell < maxx)
            & ((ix + 1) * cell > minx)
            & (iy * cell < maxy)
            & ((iy + 1) * cell > miny)
        )
        if not len(candidate):
            continue
        overlap = area(intersection(geometries[candidate], geom))
        total[candidate] += overlap
        replace = overlap > best[candidate]
        if np.any(replace):
            selected = candidate[replace]
            best[selected] = overlap[replace]
            city_name[selected] = row.gba_city
    return total, best, city_name


def water_layers(
    city_wgs: gpd.GeoDataFrame,
    dst_crs: CRS,
    transform: Affine,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    aoi_wgs = unary_union(city_wgs.geometry)
    aoi_bounds = aoi_wgs.bounds
    water_aoi = np.zeros((height, width), dtype="float32")
    valid_aoi = np.zeros((height, width), dtype="float32")

    for source_path in sorted(GSW_DIR.glob("occurrence_*.tif")):
        with rasterio.open(source_path) as src:
            left = max(aoi_bounds[0], src.bounds.left)
            bottom = max(aoi_bounds[1], src.bounds.bottom)
            right = min(aoi_bounds[2], src.bounds.right)
            top = min(aoi_bounds[3], src.bounds.top)
            if left >= right or bottom >= top:
                continue
            window = src.window(left, bottom, right, top).round_offsets().round_lengths()
            occurrence = src.read(1, window=window)
            src_transform = src.window_transform(window)
            aoi_native = rasterize(
                [(aoi_wgs, 1)],
                out_shape=occurrence.shape,
                transform=src_transform,
                fill=0,
                all_touched=False,
                dtype="uint8",
            )
            valid_native = ((occurrence != 255) & (aoi_native == 1)).astype("uint8")
            water_native = (
                (occurrence >= 90) & (occurrence <= 100) & (aoi_native == 1)
            ).astype("uint8")

            for source, destination in (
                (water_native, water_aoi),
                (valid_native, valid_aoi),
            ):
                temp = np.zeros((height, width), dtype="float32")
                reproject(
                    source=source,
                    destination=temp,
                    src_transform=src_transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    src_nodata=None,
                    dst_nodata=0,
                    resampling=Resampling.average,
                    init_dest_nodata=True,
                )
                np.maximum(destination, temp, out=destination)
    return water_aoi, valid_aoi


def save_water_raster(
    water_aoi: np.ndarray,
    valid_aoi: np.ndarray,
    transform: Affine,
    crs: CRS,
) -> None:
    WATER_RASTER.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": water_aoi.shape[0],
        "width": water_aoi.shape[1],
        "count": 2,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    with rasterio.open(WATER_RASTER, "w", **profile) as dst:
        dst.write(water_aoi, 1)
        dst.write(valid_aoi, 2)
        dst.set_band_description(1, "permanent_water_and_aoi_fraction_of_full_cell")
        dst.set_band_description(2, "valid_gsw_and_aoi_fraction_of_full_cell")


def split_for_city(city: str) -> str:
    groups = {
        "Guangzhou": "D",
        "Foshan": "D",
        "Dongguan": "D",
        "Shenzhen": "H1",
        "Huizhou": "H1",
        "Zhuhai": "H2",
        "Zhongshan": "H2",
        "Jiangmen": "H2",
        "Zhaoqing": "H2",
        "Hong Kong": "contextual",
        "Macao": "contextual",
    }
    return groups.get(city, "outside")


def main() -> None:
    contract_raw = CONTRACT_PATH.read_bytes()
    contract = json.loads(contract_raw)
    primary = int(contract["grid"]["primary_m"])
    sensitivity = int(contract["grid"]["sensitivity_m"])
    if primary != 500 or sensitivity != 1000:
        raise RuntimeError("This builder implements the frozen 500 m / 1 km grid only")
    crs = CRS.from_user_input(contract["grid"]["crs"])

    cities_wgs = gpd.read_file(BOUNDARY_PATH)[["gba_city", "geometry"]]
    cities = cities_wgs.to_crs(crs)
    ix0, ix1, iy0, iy1 = grid_indices(cities.total_bounds, primary)
    width = ix1 - ix0 + 1
    height = iy1 - iy0 + 1
    cols = np.tile(np.arange(width, dtype="int32"), height)
    rows = np.repeat(np.arange(height, dtype="int32"), width)
    ix = ix0 + cols
    iy = iy1 - rows
    geoms = box(
        ix.astype("float64") * primary,
        iy.astype("float64") * primary,
        (ix.astype("float64") + 1) * primary,
        (iy.astype("float64") + 1) * primary,
    )
    transform = from_origin(ix0 * primary, (iy1 + 1) * primary, primary, primary)

    aoi_area, city_area, city_name = city_overlaps(geoms, ix, iy, cities, primary)
    aoi_fraction = np.clip(aoi_area / (primary * primary), 0, 1)
    water_aoi_full, valid_aoi_full = water_layers(
        cities_wgs, crs, transform, width, height
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        water_within = np.where(aoi_fraction > 0, water_aoi_full.ravel() / aoi_fraction, np.nan)
        valid_within = np.where(aoi_fraction > 0, valid_aoi_full.ravel() / aoi_fraction, np.nan)
    water_within = np.clip(water_within, 0, 1)
    valid_within = np.clip(valid_within, 0, 1)

    retain = aoi_fraction > 0
    min_overlap = float(contract["grid"]["min_aoi_overlap"])
    max_water = float(contract["land"]["max_permanent_water_fraction_within_aoi"])
    min_valid = float(contract["land"]["min_gsw_valid_fraction_within_aoi"])
    water_eligible = (water_within <= max_water) & (valid_within >= min_valid)
    mainland = ~np.isin(city_name, ["Hong Kong", "Macao", ""])
    analysis_eligible = (
        (aoi_fraction >= min_overlap) & water_eligible & mainland
    )

    table = pd.DataFrame(
        {
            "grid_id": [f"t500_x{x:+06d}_y{y:+06d}" for x, y in zip(ix[retain], iy[retain])],
            "grid_x_index": ix[retain],
            "grid_y_index": iy[retain],
            "raster_row": rows[retain],
            "raster_col": cols[retain],
            "aoi_overlap_fraction": aoi_fraction[retain],
            "city_overlap_fraction": city_area[retain] / (primary * primary),
            "gba_city": city_name[retain],
            "split_group": [split_for_city(x) for x in city_name[retain]],
            "gsw_valid_fraction_within_aoi": valid_within[retain],
            "permanent_water_fraction_within_aoi": water_within[retain],
            "water_eligible": water_eligible[retain],
            "analysis_eligible": analysis_eligible[retain],
            "block_10km": [f"b10_x{math.floor(x / 20):+05d}_y{math.floor(y / 20):+05d}" for x, y in zip(ix[retain], iy[retain])],
            "parent_1km_id": [f"t1000_x{math.floor(x / 2):+06d}_y{math.floor(y / 2):+06d}" for x, y in zip(ix[retain], iy[retain])],
        }
    )
    grid500 = gpd.GeoDataFrame(table, geometry=geoms[retain], crs=crs)
    OUT_500.parent.mkdir(parents=True, exist_ok=True)
    grid500.to_parquet(OUT_500, index=False)
    save_water_raster(water_aoi_full, valid_aoi_full, transform, crs)

    # Aggregate nested 2x2 primary cells to the frozen 1 km sensitivity grid.
    grouped = defaultdict(list)
    for idx, parent in enumerate(grid500["parent_1km_id"]):
        grouped[parent].append(idx)
    rows_1km = []
    geoms_1km = []
    for parent, indices in sorted(grouped.items()):
        part = grid500.iloc[indices]
        px = math.floor(int(part.iloc[0]["grid_x_index"]) / 2)
        py = math.floor(int(part.iloc[0]["grid_y_index"]) / 2)
        aoi_area_sum = float((part["aoi_overlap_fraction"] * primary * primary).sum())
        water_area_sum = float(
            (
                part["permanent_water_fraction_within_aoi"]
                * part["aoi_overlap_fraction"]
                * primary
                * primary
            ).sum()
        )
        valid_area_sum = float(
            (
                part["gsw_valid_fraction_within_aoi"]
                * part["aoi_overlap_fraction"]
                * primary
                * primary
            ).sum()
        )
        city_areas = (
            part.groupby("gba_city", dropna=False)["city_overlap_fraction"].sum()
            * primary
            * primary
        )
        city = str(city_areas.idxmax()) if len(city_areas) else ""
        overlap = min(1.0, aoi_area_sum / (sensitivity * sensitivity))
        water = water_area_sum / aoi_area_sum if aoi_area_sum else np.nan
        valid = valid_area_sum / aoi_area_sum if aoi_area_sum else np.nan
        water_ok = bool(water <= max_water and valid >= min_valid)
        eligible = bool(
            overlap >= min_overlap
            and water_ok
            and city not in {"Hong Kong", "Macao", ""}
        )
        rows_1km.append(
            {
                "grid_id": parent,
                "grid_x_index": px,
                "grid_y_index": py,
                "aoi_overlap_fraction": overlap,
                "gba_city": city,
                "split_group": split_for_city(city),
                "gsw_valid_fraction_within_aoi": valid,
                "permanent_water_fraction_within_aoi": water,
                "water_eligible": water_ok,
                "analysis_eligible": eligible,
                "block_10km": f"b10_x{math.floor(px / 10):+05d}_y{math.floor(py / 10):+05d}",
            }
        )
        geoms_1km.append(
            box(
                px * sensitivity,
                py * sensitivity,
                (px + 1) * sensitivity,
                (py + 1) * sensitivity,
            )
        )
    grid1000 = gpd.GeoDataFrame(rows_1km, geometry=geoms_1km, crs=crs)
    grid1000.to_parquet(OUT_1000, index=False)

    def counts(frame: gpd.GeoDataFrame) -> dict:
        eligible = frame[frame["analysis_eligible"]]
        return {
            "rows_with_any_aoi_overlap": int(len(frame)),
            "analysis_eligible": int(len(eligible)),
            "eligible_by_city": {
                str(k): int(v)
                for k, v in eligible.groupby("gba_city").size().sort_index().items()
            },
            "eligible_by_split": {
                str(k): int(v)
                for k, v in eligible.groupby("split_group").size().sort_index().items()
            },
        }

    metadata = {
        "builder": "build_transport_analysis_grid.py",
        "contract_version": contract["contract_version"],
        "contract_sha256": hashlib.sha256(contract_raw).hexdigest(),
        "crs": crs.to_proj4(),
        "grid_anchor": "integer multiples of cell size from LAEA false easting/northing zero",
        "outcome_data_read": False,
        "water_rule": {
            "source": contract["land"]["permanent_water"],
            "max_fraction_within_aoi": max_water,
            "min_valid_fraction_within_aoi": min_valid,
        },
        "grid_500m": counts(grid500),
        "grid_1000m": counts(grid1000),
        "outputs": {
            "grid_500m": str(OUT_500.relative_to(ROOT)),
            "grid_500m_sha256": sha256(OUT_500),
            "grid_1000m": str(OUT_1000.relative_to(ROOT)),
            "grid_1000m_sha256": sha256(OUT_1000),
            "water_raster": str(WATER_RASTER.relative_to(ROOT)),
            "water_raster_sha256": sha256(WATER_RASTER),
        },
    }
    METADATA.parent.mkdir(parents=True, exist_ok=True)
    METADATA.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
