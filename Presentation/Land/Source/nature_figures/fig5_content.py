"""Figure 5 assertions and identities; no plotting imports.

Retain P29/P28, P15/P28 and P20/P25 maximum/minimum equal-city selections.
Detail g includes all 28 negative P29 cells, with all signs displayed.
Coverage details preserve the original nonzero-extent crop plus 1.5 km.
"""
METRICS = {
    "total_opportunity_contribution": "population_weighted_total_opportunity_contribution",
    "cross_city_opportunity_contribution": "population_weighted_cross_city_opportunity_contribution",
    "coverage_contribution": "population_weighted_coverage_contribution",
}
TITLES = ["Total opportunity", "Outside-origin-city opportunity", "Coverage"]
EXPECTED = {"a": "P29", "b": "P15", "c": "P20", "d": "P28", "e": "P28", "f": "P25"}
NAMES = {"P29": "Guangzhou Line 11 composite", "P15": "Foshan Line 2 (phase 1)",
         "P20": "Foshan Line 3 (first section)", "P28": "Haizhu Tram section closure",
         "P25": "Gaoming Tram suspension"}
OWNING_SECTION = "Results: Contrasting event functions and spatial footprints"
STEM = "fig4_project_spatial_footprints"
CANVAS = (183, 202)
# Lower-left placement in millimetres. No scaling during assembly.
PANELS = [("a",3,141,57,46),("b",63,141,57,46),("c",123,141,57,46),
          ("d",3,86,57,46),("e",63,86,57,46),("f",123,86,57,46),
          ("g",3,15,108,49),("h",114,15,40,49),("i",157,15,23,49)]
