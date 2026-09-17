# Tri-city rail accessibility

Code, data and geographic figures for **Attributing Metropolitan Accessibility Change to Rail Events: A Spatial Shapley Analysis of Guangzhou–Foshan–Dongguan, 2018–2024**.

Shuxin JIN and Di WANG. Corresponding author: Di WANG, cea_wangd@ujn.edu.cn.
Prepared for submission to *ISPRS International Journal of Geo-Information*. This repository does not imply publication or acceptance. The unpublished manuscript and internal manuscript-review reports are not included.

## What the study measures

The study allocates annual standardized accessibility change among 29 rail-event packages using exact within-year, cell-level Shapley values. It distinguishes total population opportunity, opportunity outside the origin municipality, and 15-minute walking access to an active station. Guangzhou, Foshan and Dongguan are the origin cities; the destination inventory covers nine mainland Greater Bay Area cities.

The reference analysis uses a fixed 2023 WorldPop opportunity surface, fixed geometry inputs and common service parameters. It describes network counterfactuals, not observed historical journey times, ridership or causal project effects. There are 50,607 valid origins and 265 missing-snap origins. The 2017 baseline and seven event years comprise 196 within-year coalition states.

## Repository contents

- `Codes/`: analysis, preprocessing, acquisition, replay and numerical-check scripts, with frozen configurations.
- `DataBundles/`: four ZIP files containing numerical outputs, frozen routing inputs and rendered figures. Extract them **into the repository root** before running the scripts.
- `Data/metadata/`: source URLs, versions and processing provenance. Raw third-party products and archived source webpages are not uploaded.
- `Results/`: machine-readable tables, figure source values and selected numerical records.
- `Figures/transport/source/`: current figure generators and editable Graphviz source. SVG/PDF figures are in `DataBundles/figures-and-table-binaries.zip`, preserving their `Figures/transport/` paths. Internal figure filenames start at `fig0`; see the mapping below.
- `Environment/`: recorded dependency versions and system tools.
- `Docs/`: reproduction instructions, variables, provenance and licensing boundaries.
- `FILE_MANIFEST.csv`: original and public-copy hashes for the curated source files. Data-file entries refer to files inside the bundles.

## Start here

```bash
git clone https://github.com/winnieks7/tri-city-rail-accessibility.git
cd tri-city-rail-accessibility
python3 Codes/release/unpack_data.py
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r Environment/requirements-lock.txt
python Codes/manuscript/replay_transport_d_derived_results.py --output-dir Reproduced/derived
```

The final command reconstructs summaries from retained cell outputs. It does **not** rerun routing or Shapley attribution, and refuses an existing nonempty output directory. See [reproduction instructions](Docs/REPRODUCING.md) before attempting any other run. The recorded lockfile describes the original environment; installing the complete lockfile on every platform has not been independently tested.

The public-copy derived-summary replay passed on 17 September 2026. The maximum event/stratum difference from retained reference summaries was approximately `1.82e-12`; see `Docs/DERIVED_REPLAY_RECEIPT.json`. This checks summaries, not a full routing/Shapley regeneration.

The repository includes frozen inputs for a separate reference replay. No new routing or Shapley run was performed to prepare this release. Historical accessibility values for each individual coalition were not retained; the retained outputs are annual endpoint surfaces, event allocations, summaries and consistency diagnostics. Internal consistency is not external validation.

## Paper-to-file mapping

| Manuscript element | Source file or generator |
| --- | --- |
| Figure 1 | `gen_fig0_workflow_schematic.py`, `fig0_workflow_graphviz_revised.dot` |
| Figure 2 | `gen_fig1_tri_city_network_evolution.py` |
| Figure 3 | `gen_fig2_accessibility_change_maps.py` |
| Figure 4 | `gen_fig3_project_rank_matrix.py` |
| Figure 5 | `gen_fig4_project_spatial_footprints.py` |
| Figure 6 | `gen_fig5_coverage_margin_decomposition.py` |
| Figure 7 | `gen_fig6_sensitivity_comparisons.py` |
| Figures A1–A6 | `gen_figs1_...py` through `gen_figs6_...py` |
| Appendix E, 29 event plates | `gen_figs7_event_detail_atlas.py` |
| Event results | `Results/tables/transport_d_project_summary.csv` |
| Event sources and dates | `Results/tables/transport_d_event_source_topology_ledger.csv` |
| Coverage-stratum decomposition | `Results/tables/transport_d_event_stratum_summary.csv` |

Generators are under `Figures/transport/source/`. Map regeneration requires separately acquired GADM boundaries; they are not bundled. The figure files correspond to the 17 September 2026 manuscript presentation, including percentage-point units in Figure 7.

## Data sources and permissions

Contains information derived from **© OpenStreetMap contributors**, distributed under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). WorldPop population inputs require CC BY 4.0 attribution. Water-mask source: EC JRC/Google, Global Surface Water v1.4. Administrative assignment and map boundaries use GADM 4.1.

GADM boundary datasets are **not redistributed**. The supplied grid consists of regular analytical squares, not clipped administrative polygons. Obtain GADM from its provider subject to its terms. See [data sources](Docs/DATA_SOURCES.md) and [licensing scope](LICENSES.md). Open licensing of our code does not override upstream database rights.

## Citation and version

Please cite the repository authors, title, release version and URL; see `CITATION.cff`. Version `v1.0.0` is the initial public research-materials release. No article DOI or repository DOI has been assigned in this deposit. GitHub provides the access route; a separately archived DOI can be added later without changing the frozen scientific results.

## License

Original software is MIT licensed. Original documentation and independently licensable research results are CC BY 4.0. Third-party and derived database rights remain applicable as described in `LICENSES.md`; the numerical data bundles are **not** blanket MIT-licensed datasets.
