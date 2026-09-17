#!/usr/bin/env python3
"""Build the GBA study boundary from GADM 4.1 ADM2 polygons."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "Data/raw/boundaries/gadm41_CHN_2.json"
CONFIG = ROOT / "Codes/config/study_area.json"
OUT_DIR = ROOT / "Data/interim/aoi"


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    adm2 = gpd.read_file(SOURCE)
    mainland = set(config["mainland_prefectures"])

    selected = adm2[
        ((adm2["NAME_1"] == "Guangdong") & adm2["NAME_2"].isin(mainland))
        | adm2["NAME_1"].isin(["HongKong", "Macau"])
    ].copy()
    if selected.empty:
        raise RuntimeError("No GBA administrative units matched the configured names")

    selected["gba_city"] = selected["NAME_2"]
    selected.loc[selected["NAME_1"] == "HongKong", "gba_city"] = "Hong Kong"
    selected.loc[selected["NAME_1"] == "Macau", "gba_city"] = "Macao"

    city = selected.dissolve(by="gba_city", as_index=False, aggfunc="first")
    boundary = city.assign(study_area="GBA").dissolve(by="study_area", as_index=False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    selected.to_file(OUT_DIR / "gba_source_adm2.geojson", driver="GeoJSON")
    city.to_file(OUT_DIR / "gba_city_boundaries.geojson", driver="GeoJSON")
    boundary.to_file(OUT_DIR / "gba_boundary.geojson", driver="GeoJSON")

    summary = {
        "source": "GADM 4.1 China ADM2",
        "source_file": str(SOURCE.relative_to(ROOT)),
        "selected_source_features": int(len(selected)),
        "city_units": city["gba_city"].sort_values().tolist(),
        "bounds_wgs84": [round(v, 6) for v in boundary.total_bounds.tolist()],
        "crs": str(boundary.crs),
        "license_note": "GADM data are permitted for academic and non-commercial use; verify terms before redistribution.",
    }
    (OUT_DIR / "gba_boundary_metadata.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
