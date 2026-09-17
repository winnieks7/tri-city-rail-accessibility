# Variables and units

`data-schema.json` lists all included Parquet files, row counts and exact column types. The principal records are:

| Record or field | Meaning |
| --- | --- |
| `d_annual_accessibility_cell.parquet` | 406,976 origin-year records, including missing-snap origins, for 2017–2024 |
| `d_project_attribution_cell.parquet` | 1,475,288 origin-event records, including missing-snap origins, for 29 events |
| `grid_id` | Stable 500-m analysis-cell identifier; joins to `transport_grid_500m.parquet` |
| `grid_x_index`, `grid_y_index` | Integer cell coordinates under the recorded Lambert azimuthal equal-area grid |
| `city` / `gba_city` | Assigned municipality; exact names are preserved in the data |
| `year` | Annual year-end topology or event year |
| `event_id` | Frozen package identifier; P01–P29 follow chronological year/identifier order |
| `population_weight` | Allocated modeled 2023 WorldPop people used to weight origins |
| `total_opportunity` | Gravity-decayed population reachable under standardized rail-mediated paths, effective people |
| `cross_city_opportunity` | Effective people assigned outside the origin municipality; not cross-city trip counts |
| `coverage` | 0/1 indicator for 15-minute walking access to an active station |
| `*_contribution` | Exact within-year Shapley allocation; opportunity in effective people, coverage in fractions |
| `baseline_coverage` | Origin's coverage at the start of its event year, not a fixed socioeconomic group |
| `analysis_status` | `missing_walk_snap` is excluded; `structural_zero` is a valid zero; `routable` means successfully snapped but does not guarantee station access |
| `area_weight_m2` | Effective retained non-water analysis area in square metres |
| `split_group` | Historical preprocessing assignment; only the D tri-city origin case is analyzed in the paper |
| `r0`, `r2`, `r3` labels | Reference, conservative impedance and alternative connector, respectively; some latter checks are exploratory |

Regional population-weighted values are the equal mean of three within-city population-weighted means. They are not a pooled population mean unless explicitly labeled. Multiply coverage fractions by 100 for percentage points. Missing measurements remain missing/NaN rather than becoming structural zeros. Names ending in `_1km` refer to nested aggregation and complete-parent support, not an independently rerouted 1-km origin experiment.

## Coverage-stratum fields

The legacy columns `population_weighted_total_contribution_uncovered` and `population_weighted_total_contribution_covered` in `Results/tables/transport_d_project_summary.csv` are **conditional stratum means**, not additive components of an event's total contribution. Within each city, the population-weighted contribution numerator is divided by that stratum's population. The regional row then averages the city-level conditional means. These two columns must not be added or used to calculate the manuscript's stratum shares. They are retained unchanged for compatibility with the original outputs.

For the manuscript's additive decomposition, use `additive_population_weighted_contribution` in `Results/tables/transport_d_baseline_coverage_decomposition.csv`, or the paired `<metric>_baseline_uncovered` and `<metric>_baseline_covered` columns in `Results/tables/transport_d_event_stratum_summary.csv`. Each city's stratum numerator is divided by the **full valid city population**, before taking the equal-city mean. The two components therefore sum to the corresponding event contribution, subject to numerical precision. Coverage groups are reassigned at each event-year start, not fixed across the study period.

For example, the total-opportunity components for Qingtang infill station activation (`D2018_E02_GZ_M9_QINGTANG`) are 76.0972 and 68.2837 effective people, summing to 144.3809. The legacy conditional means are 99.6345 and 306.0788 and do not form that decomposition.

## Coordinate reference systems

GeoParquet files store coordinate reference metadata. The main grid uses `+proj=laea +lat_0=22.8 +lon_0=113.5 +datum=WGS84 +units=m +no_defs`. Track/station source layers may use geographic coordinates; read each file's CRS before combining layers.
