"""Retained Figure 2 data, independently of rendering.

Expected: 50,607 valid origins; 254 baseline arcs; 254 first-activated arcs.
All records belong to Materials and Methods, Section 2.1 / Figure 2.
"""
from pathlib import Path
import hashlib
import json
import geopandas as gpd
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PAPER = ROOT / 'Presentation/Land'
REV = PAPER / 'Generated/figure2'
OUT = REV / 'panels'
STEM = 'fig1_tri_city_network_evolution'
CRS = '+proj=laea +lat_0=22.8 +lon_0=113.5 +datum=WGS84 +units=m +no_defs'
TARGETS = ['Guangzhou', 'Foshan', 'Dongguan']
REGION_LONLAT = (111.05, 21.30, 115.70, 24.65)
INPUTS = {
    'cities': ROOT / 'Data/interim/aoi/gba_city_boundaries.geojson',
    'gadm': ROOT / 'Data/raw/boundaries/gadm41_CHN_2.json',
    'tracks': ROOT / 'Data/interim/transport/d_annual_active_track_edges.parquet',
    'land': HERE / 'context_data/ne_110m_land.zip',
}

def load():
    cities = gpd.read_file(INPUTS['cities']).to_crs(CRS)
    tracks = gpd.read_parquet(INPUTS['tracks']).to_crs(CRS)
    keys = ['sequence_id', 'route_identity', 'from_order', 'to_order']
    base = tracks.loc[tracks.year.eq(2017)].drop_duplicates(keys)
    current = tracks.loc[tracks.year.eq(2024)].drop_duplicates(keys)
    first = tracks.groupby(keys, as_index=False).year.min().rename(columns={'year':'first_active_year'})
    additions = tracks.sort_values('year').drop_duplicates(keys).merge(first, on=keys, validate='one_to_one')
    additions = gpd.GeoDataFrame(additions.loc[additions.first_active_year.gt(2017)], crs=tracks.crs)
    assert len(base) == 254 and len(additions) == 254
    return cities, tracks, base, current, additions

def record_values():
    cities, tracks, base, current, additions = load()
    previous = json.loads((PAPER/'ReferenceValues'/f'{STEM}.json').read_text())
    assert len(base) == previous['active_route_sequence_arcs_2017']
    assert len(current) == previous['active_route_sequence_arcs_2024']
    assert len(additions) == previous['route_sequence_arcs_first_activated_2018_2024']
    assert {str(y):int(additions.first_active_year.eq(y).sum()) for y in range(2018,2025)} == previous['first_activation_route_sequence_arc_counts']
    REV.mkdir(parents=True, exist_ok=True)
    (REV/'values.json').write_text(json.dumps(previous,indent=2)+'\n')
    rows = [{'panel':'b','row':'baseline','column':'arc_count','value':len(base),'owning_section':'2.1 / Figure 2'}]
    rows += [{'panel':'c','row':str(y),'column':'first_active_arc_count','value':int(additions.first_active_year.eq(y).sum()),'owning_section':'2.1 / Figure 2'} for y in range(2018,2025)]
    pd.DataFrame(rows).to_csv(REV/'source_data.csv',index=False)
    (REV/'input_manifest.json').write_text(json.dumps({k:{'path':str(p.relative_to(ROOT)), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for k,p in INPUTS.items()},indent=2)+'\n')

if __name__ == '__main__':
    record_values()
