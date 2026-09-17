# Reproduction guide

## Levels of reproduction

1. **Inspect tables and figures**. CSV/JSON results are browsable directly. Extract `DataBundles/figures-and-table-binaries.zip` for the current SVG/PDF figures and Parquet summary tables.
2. **Rebuild summaries from retained cell outputs**. Extract all four bundles at the repository root and run `Codes/manuscript/replay_transport_d_derived_results.py --output-dir Reproduced/derived` in the recorded Python environment. The archived 27 August 2026 derived-summary receipt is included. A separate release-preparation check is reported only if actually executed.
3. **Regenerate figures**. Acquire GADM 4.1 China ADM2 from the provider and run `Codes/preprocess/build_aoi.py` to generate the excluded `Data/interim/aoi/gba_city_boundaries.geojson`. Figure scripts use retained results, not new accessibility outcomes. Graphviz is required for Figure 1. Font differences can change layout. Figure output folders should be copied or backed up before regeneration.
4. **Independent reference replay**. `Codes/analysis/replay_transport_d_project_attribution.py --output-dir Reproduced/reference` reads supplied frozen routing inputs and writes only into a new empty output directory. This is a new nonconfirmatory replication, not a repeat of the original outcome opening. It was not executed to prepare this release. No end-to-end equivalence or performance benchmark is claimed.
5. **Rebuild from upstream raw data**. Acquisition metadata and preprocessing code are supplied, but raw rasters, full OSM extracts, GADM boundaries and official webpages are not bundled. Contemporary downloads may differ from the archived snapshots. A source rebuild is not guaranteed byte-identical and must be conducted in a separate workspace.

Do not execute the original one-time `run_transport_d_project_attribution.py` or sensitivity opening scripts over this archive. They are retained as implementation records and dependencies. No distinct R1 sensitivity exists because reference track geometry already uses archived OSM relations. Do not describe R1 as performed.

## Scientific interpretation

- The reference values are standardized network potential, not historical passenger experience or causal effects.
- Opportunity magnitudes depend on impedance, opportunity surface, municipal assignment and regional weighting. The reported sensitivity results include small-value sign exceptions.
- Coverage strata are reclassified at each event-year start. The manuscript's additive stratum components use the full city population denominator before averaging city results. The legacy `_contribution_uncovered` and `_contribution_covered` columns in `transport_d_project_summary.csv` instead contain conditional stratum means and must not be summed. See [Coverage-stratum fields](DATA_DICTIONARY.md#coverage-stratum-fields) for the authoritative additive fields and an example.
- `routable` in retained origin files means a routing-relevant origin was successfully snapped, not that it has a qualifying station connection. Similarly, snapped destination pixels need not have a station walking pair.
- The original individual-coalition accessibility surfaces were not saved. Annual endpoint surfaces and Shapley allocations do not identify all coalition values. Alternative order, precedence, package or year-boundary analyses require new calculations.
- Current journal-facing presentation may differ from legacy machine labels. In particular, zero-denominator destination missingness is `n/a` in the manuscript, while the frozen support CSV uses 0.0; Figure 7 displays coverage in percentage points, whereas cell-level coverage contributions are fractions.

## Historical configuration files

Some reused grid/network configurations retain titles and fields from an earlier, abandoned land-cohort design. They are preserved as immutable preprocessing records, not claimed analyses. The active attribution contract is `Codes/config/transport_project_attribution_contract_20260826_r4.json`, with event packages r2, WorldPop r1 and pedestrian graph r2. The origin inference is limited to Guangzhou, Foshan and Dongguan. Other-city grid inputs are shared preprocessing context, not a completed holdout study.

## File integrity

`FILE_MANIFEST.csv` maps files to source and public-copy hashes. Data-bundle members retain the original scientific bytes. The public figure helper changes only its QA output directory to `Results/figure_checks`; it does not change numerical inputs or plotting parameters. Reproduction scripts should use new output directories so the supplied records remain available for comparison.
