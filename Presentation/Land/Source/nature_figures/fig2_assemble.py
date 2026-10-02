"""Assemble native-size PDF and editable SVG panels without scaling."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
import fitz

HERE=Path(__file__).resolve().parent
PAPER=HERE.parents[1]
REV=PAPER/'Generated/figure2'
OUT=REV/'rendered'
PT=72/25.4
# Coordinates are mm from the lower left of the 183 × 162 mm sheet.
PANELS=[('a','fig2a_geographical_setting',5,76,173,84),
        ('b','fig2b_baseline',5,4,83,68),
        ('c','fig2c_activations',95,4,83,68)]

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    doc=fitz.open(); page=doc.new_page(width=183*PT,height=162*PT)
    ET.register_namespace('','http://www.w3.org/2000/svg')
    ET.register_namespace('xlink','http://www.w3.org/1999/xlink')
    ns='{http://www.w3.org/2000/svg}'
    svg=ET.Element(ns+'svg',{'width':f'{183*PT}pt','height':f'{162*PT}pt',
        'viewBox':f'0 0 {183*PT} {162*PT}','version':'1.1'})
    ET.SubElement(svg,ns+'rect',{'width':'100%','height':'100%','fill':'white'})
    manifest={'schema_version':1,'figure':{'width_pt':183*PT,'height_pt':162*PT},
              'panels':[],'row_groups':[{'id':'network-row','panels':['b','c']}],
              'column_groups':[], 'exemptions':[{'panels':['a'], 'checks':['row','column'],
                'reason':'Full-width geographic anchor above two equal-scale network panels; intentional asymmetric layout.'}]}
    for letter,name,x,y,w,h in PANELS:
        src=fitz.open(REV/'panels'/f'{name}.pdf')
        assert abs(src[0].rect.width-w*PT)<.3 and abs(src[0].rect.height-h*PT)<.3
        rect=fitz.Rect(x*PT,(162-y-h)*PT,(x+w)*PT,(162-y)*PT)
        page.show_pdf_page(rect,src,0,keep_proportion=True)
        raw=(REV/'panels'/f'{name}.svg').read_text()
        ids=re.findall(r'\bid="([^"]+)"',raw)
        for ident in sorted(set(ids),key=len,reverse=True):
            raw=raw.replace(f'id="{ident}"',f'id="{letter}_{ident}"')
            raw=raw.replace(f'url(#{ident})',f'url(#{letter}_{ident})')
            raw=raw.replace(f'href="#{ident}"',f'href="#{letter}_{ident}"')
        child=ET.fromstring(raw)
        group=ET.SubElement(svg,ns+'g',{'transform':f'translate({x*PT},{(162-y-h)*PT})'})
        for element in child: group.append(element)
        manifest['panels'].append({'id':letter,'bbox_pt':[x*PT,y*PT,(x+w)*PT,(y+h)*PT]})
    stem='fig1_tri_city_network_evolution'
    doc.save(OUT/f'{stem}.pdf',garbage=4,deflate=True)
    page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),alpha=False).save(OUT/f'{stem}.png')
    ET.ElementTree(svg).write(OUT/f'{stem}.svg',encoding='utf-8',xml_declaration=True)
    (REV/'placement.json').write_text(json.dumps({'unit':'mm','canvas':[183,162],
        'panels':[dict(zip(('letter','file','x','y','width','height'),p)) for p in PANELS]},indent=2)+'\n')
    (REV/'alignment_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__': main()
