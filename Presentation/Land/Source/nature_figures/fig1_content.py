"""What Figure 1 asserts, independently of its drawing code.

All coordinates below describe a labelled conceptual example, not research data.
No outcome values, ranks, geographic coordinates or effect sizes are invented.
"""
from pathlib import Path
import csv
import hashlib
import json

HERE=Path(__file__).resolve().parent
PAPER=HERE.parents[1]
PROJECT=PAPER.parents[1]
REV=PAPER/"Generated/figure1"
STEM="fig0_workflow_schematic"
CANVAS=(183,139)
PANELS=[("a",3,76,55,59),("b",64,76,55,59),("c",125,76,55,59),
        ("d",3,17,112,50),("e",124,17,56,50)]
PANEL_NAMES={"a":"fig1a_coverage","b":"fig1b_total","c":"fig1c_cross",
             "d":"fig1d_allocation","e":"fig1e_outputs","shared":"fig1_furniture"}
# Dimensionless diagram coordinates, not geographical or population observations.
CITY_LEFT=[(1,16),(4,39),(20,42),(29,37),(28,29),(29,22),(26,16),(14,12)]
CITY_RIGHT=[(29,37),(39,42),(53,39),(54,19),(43,12),(26,16),(29,22),(28,29)]
CITY_BORDER=[(29,37),(28,29),(29,22),(26,16)]
STATIONS=[(6,31),(15,27),(24,34),(37,34),(47,37),(44,23)]
RAIL_EDGES=[(0,1),(1,2),(2,3),(3,4),(3,5)]
ORIGIN=(8,17)
ORIGIN_WALK=[(8,17),(8,21),(11,21),(15,27)]
DESTINATIONS=[(15,36,2,False),(22,18,2,False),(35,39,3,True),
              (48,30,4,True),(39,18,5,True)]
NODES=[(0,0),(8,0),(16,0),(8,9),(16,9)]
PRIOR_EDGES=[(0,1),(1,2),(1,3),(3,4)]
EVENT_EDGES={"A":[(2,4)],"B":[(0,3)]}
STATES=[("Prior year-end",()),("A only",("A",)),("B only",("B",)),("A + B",("A","B"))]
METRICS=["Station-access coverage","Total population opportunity","Outside-origin-city opportunity"]
ASSERTIONS=[
    ("a","coverage","walking access to an active station within 15 min; no circular buffer","Materials and Methods: Impedance and accessibility measures"),
    ("b","total","population discounted by generalized travel time over valid walk-rail-walk paths","Materials and Methods: Impedance and accessibility measures"),
    ("c","cross-city","same total-opportunity sum restricted to destinations outside origin municipality","Materials and Methods: Impedance and accessibility measures"),
    ("a-c","example","shared illustrative geometry; equal-size population markers encode inclusion, not magnitude","Materials and Methods: Impedance and accessibility measures"),
    ("d","prior","preceding year-end network","Materials and Methods: Rail events and annual counterfactuals"),
    ("d","example","two illustrative link-addition events; not actual event identities","Materials and Methods: Rail events and annual counterfactuals"),
    ("d","allocation","exact Shapley within each year, separately for each metric and origin","Materials and Methods: Event contributions and sensitivity"),
    ("e","maps","signed event-level spatial footprints","Results: Contrasting event functions and spatial footprints"),
    ("e","profiles","population-weighted city means, then equal-city regional summary","Materials and Methods: Impedance and accessibility measures"),
    ("e","coverage","uncovered or covered at event-year start","Materials and Methods: Event contributions and sensitivity"),
    ("shared","fixed inputs","500-m origins; 2023 WorldPop; pedestrian geometry; speeds, waits and transfer penalties","Materials and Methods: Impedance and accessibility measures"),
]

def record():
    REV.mkdir(parents=True,exist_ok=True)
    with (REV/"source_data.csv").open("w",newline="") as f:
        writer=csv.writer(f); writer.writerow(["panel","element","assertion","owning_section"])
        for row in ASSERTIONS:
            assert row[-1]; writer.writerow(row)
    prior=json.loads((PAPER/"ReferenceValues"/f"{STEM}.json").read_text())
    assert (prior["events"],prior["annual_games"],prior["coalition_states"],prior["baseline"],prior["years"])==(29,7,196,2017,[2018,2024])
    # Preserve the approved conceptual dependency graph and factual anchors.
    (REV/"values.json").write_text(json.dumps(prior,indent=2)+"\n")
    paths=[PROJECT/"Results/transport_d_accessibility_opening.json",PROJECT/"CITATION.cff"]
    frozen=json.loads(paths[0].read_text())
    for name,value in frozen["outputs"].items():
        assert hashlib.sha256((PROJECT/name).read_bytes()).hexdigest()==value["sha256"]
    manifest={"inputs":{str(p.relative_to(PROJECT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              "schematic_not_empirical":True,"research_runs_executed":0,"retained_anchors":prior,
              "example_nodes":NODES,"example_prior_edges":PRIOR_EDGES,"example_event_edges":EVENT_EDGES,
              "example_states":STATES,"schematic_stations":STATIONS,
              "schematic_destinations":DESTINATIONS,"population_symbols_encode":"inclusion, not magnitude",
              "scientific_output_hashes":frozen["outputs"]}
    (REV/"input_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
