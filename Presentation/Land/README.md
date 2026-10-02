# Land presentation, version 1.1.0

Figure materials for **Rail Network Change and the Geography of Metropolitan
Accessibility Gains**, prepared for submission to *Land*. No publication or
acceptance is implied. The manuscript and internal review records are not included.

This addendum updates presentation only. The retained 29-event allocations, annual
surfaces and sensitivity results are unchanged. The original presentation remains
available at v1.0.0 and in the legacy `Figures/transport` directory.

## Contents and figure mapping

| Current item | Filename stem / source entry point |
| --- | --- |
| Figure 1: spatial definitions and attribution | `fig0_workflow_schematic` |
| Figure 2: geographical setting and network change | `fig1_tri_city_network_evolution` |
| Figure 3: annual levels and change | `fig2_accessibility_change_maps` |
| Figure 4: event contribution profiles | `fig3_project_rank_matrix` |
| Figure 5: spatial footprints and local details | `fig4_project_spatial_footprints` |
| Figure 6: coverage-group decomposition | `fig5_coverage_margin_decomposition` |
| Figures S1–S6: annual and all-event atlases | `figs1_...` through `figs6_...` |
| Supplementary Section 3: 29 event plates (not separately numbered figures) | `figs7_event_detail_atlas` |
| Figure S7: study design | duplicate of Figure 1 |
| Figure S8: sensitivity comparisons | `fig6_sensitivity_comparisons` |

`Figures/` contains six main figures; `SupplementaryFigures/` contains the
supplementary PDF/SVG files and individual event-plate SVGs. `Source/nature_figures/`
contains the Python renderers. `ReferenceValues/` preserves numerical plotting
anchors. SVG typography and linework are editable; cell maps retain embedded
rasters, without spatial smoothing. `MANIFEST.json` describes the supplied files.

## Regenerate the figures

1. Download the repository at v1.1.0 and extract its four data bundles with
   `python Codes/release/unpack_data.py`.
2. Extract the release attachment `Land_Presentation_v1.1.0.zip` into that same
   repository root. The addendum belongs at `Presentation/Land/`.
3. Install the recorded scientific Python dependencies in `Environment/`.
   The new panel assemblers additionally require **PyMuPDF** (`pip install
   pymupdf`). Matplotlib, NumPy, pandas, GeoPandas, PyArrow and Pillow are used.
   Arial is preferred; substituting fonts may change text layout.
4. Acquire GADM 4.1 China ADM2 separately under its terms, place the JSON at
   `Data/raw/boundaries/gadm41_CHN_2.json`, and run
   `python Codes/preprocess/build_aoi.py`. These administrative geometries are
   not redistributed here. The included Natural Earth locator is public domain;
   see `Source/nature_figures/context_data/README.md`.
5. Run the desired renderer from the repository root:

```bash
python Presentation/Land/Source/nature_figures/gen_fig0_workflow_schematic.py
python Presentation/Land/Source/nature_figures/fig1_assemble.py
python Presentation/Land/Source/nature_figures/gen_fig1_tri_city_network_evolution.py
python Presentation/Land/Source/nature_figures/fig2_assemble.py
python Presentation/Land/Source/nature_figures/gen_fig2_accessibility_change_maps.py
python Presentation/Land/Source/nature_figures/gen_fig3_project_rank_matrix.py
python Presentation/Land/Source/nature_figures/gen_fig4_project_spatial_footprints.py
python Presentation/Land/Source/nature_figures/fig5_assemble.py
python Presentation/Land/Source/nature_figures/gen_fig5_coverage_margin_decomposition.py
```

The `gen_figs*.py` scripts create supplementary atlases; run
`gen_fig6_sensitivity_comparisons.py` for Figure S8. Outputs go to
`Presentation/Land/Generated/` and do not overwrite supplied publication figures.
Figures 1, 2 and 5 use native-size panel assembly. Figure 1 is a labelled conceptual
example and does not require Graphviz. Its population symbols indicate inclusion,
not measured values. Figure 2 and the event overlays reconstruct geometry only;
no accessibility outcomes are recomputed.

Opportunity-level colourbars in Figure 3 and Figures S1/S2 use log1p-transformed
colours with ticks in raw effective-population units. Signed changes retain
their symmetric-log mapping and signed raw-unit ticks. Display limits and
scientific values have not changed.

## Licensing

Original software: MIT. Original documentation and independently licensable
research results: CC BY 4.0. Third-party and derived-database rights, including
OpenStreetMap ODbL and WorldPop attribution, remain applicable. See the repository
`LICENSES.md`. Neither raw GADM files nor other raw source products are included.
