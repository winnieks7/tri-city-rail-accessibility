# Sources and access routes

| Source | Role | Access |
| --- | --- | --- |
| WorldPop Global2 R2025A, China 2023, constrained UN-adjusted, approximately 1 km | Fixed opportunity surface and origin weights | Source URL and SHA-256 in `Codes/config/transport_worldpop_2023.json`; derived pixels and weights in `frozen-inputs.zip`; raw raster excluded |
| OpenStreetMap via Geofabrik | Fixed pedestrian graph, embedded extract timestamp 24 August 2026 | `Data/metadata/transport/guangdong_geofabrik_20260826.json`; relevant frozen snaps and walking pairs included, full raw extract and full pedestrian graph excluded |
| OpenStreetMap via separate Overpass downloads | Track geometry and candidate station sequences | `osm_d_route_members_20260826.json`, `osm_hz1_route_members_20241101_20260826.json`, `osm_gaoming_tram_geometry_20260826.json` under source metadata; query files and derived route inputs included |
| GADM 4.1 China ADM2 | Administrative assignment and map outlines | [Provider](https://gadm.org/download_country.html); [terms](https://gadm.org/license.html); raw/dissolved boundaries excluded, `Codes/preprocess/build_aoi.py` supplied |
| JRC Global Surface Water v1.4, 1984–2021 | Permanent-water exclusion | `Data/metadata/jrc_gsw_v1_4_occurrence.json`; acquisition script included, original raster tiles excluded |
| Agency/operator and contemporary institutional reporting | Event dates and operational/topological changes | `Results/tables/transport_d_event_source_topology_ledger.csv`; full archived webpages/PDFs excluded |

For the boundary builder, obtain `gadm41_CHN_2.json.zip` from `https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_CHN_2.json.zip`, subject to GADM terms, and extract `gadm41_CHN_2.json` into `Data/raw/boundaries/`. Then run `python Codes/preprocess/build_aoi.py`. This step should not rebuild or replace the supplied regular analysis-grid data.

The Haizhu Tram supplement is a historical relation at **1 November 2024**, not a 2026 replacement geometry. Operational dates and annual station/connection states are controlled by the frozen event/source rules, not the current OSM defaults.

Some original URLs subsequently became unavailable; replacement institutional source records are identified in the included provenance metadata. Those replacements document the same events and did not change event dates, packages or outcomes. No claim is made that every upstream URL remains live.

## Dataset citations

- WorldPop, University of Southampton. Global2 R2025A population estimates, constrained UN-adjusted China 2023, approximately 1 km. Exact product URL and version in the WorldPop configuration.
- OpenStreetMap contributors. OpenStreetMap database. https://www.openstreetmap.org/copyright . Extract and historical-query dates are listed above.
- European Commission Joint Research Centre/Google. Global Surface Water v1.4, occurrence, 1984–2021. https://global-surface-water.appspot.com/download .
- GADM. Database of Global Administrative Areas, version 4.1, China ADM2. https://gadm.org/ .

No repository DOI has been minted. A GitHub release URL/commit identifies this version but is not a DOI or a substitute for a separate preservation service.
