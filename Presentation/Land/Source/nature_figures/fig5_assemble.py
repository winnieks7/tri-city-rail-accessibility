"""Compose independently rendered Figure 5 panels at native physical size."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
import fitz
from fig5_content import PANELS,CANVAS,STEM
HERE=Path(__file__).resolve().parent
REV=HERE.parents[1]/"Generated/figure5"
PT=72/25.4

def main():
    out=REV/"rendered"; out.mkdir(exist_ok=True)
    w,h=CANVAS; doc=fitz.open(); page=doc.new_page(width=w*PT,height=h*PT)
    ET.register_namespace("","http://www.w3.org/2000/svg")
    ET.register_namespace("xlink","http://www.w3.org/1999/xlink")
    ns="{http://www.w3.org/2000/svg}"
    svg=ET.Element(ns+"svg",{"width":f"{w*PT}pt","height":f"{h*PT}pt",
        "viewBox":f"0 0 {w*PT} {h*PT}","version":"1.1"})
    items=[("furniture",0,0,w,h),*PANELS]
    for letter,x,y,pw,ph in items:
        name="fig5_furniture" if letter=="furniture" else f"fig5{letter}"
        src=fitz.open(REV/"panels"/f"{name}.pdf")
        assert abs(src[0].rect.width-pw*PT)<.01 and abs(src[0].rect.height-ph*PT)<.01
        rect=fitz.Rect(x*PT,(h-y-ph)*PT,(x+pw)*PT,(h-y)*PT)
        page.show_pdf_page(rect,src,0,keep_proportion=True)
        raw=(REV/"panels"/f"{name}.svg").read_text()
        for ident in sorted(set(re.findall(r'\bid="([^"]+)"',raw)),key=len,reverse=True):
            raw=raw.replace(f'id="{ident}"',f'id="{letter}_{ident}"')
            raw=raw.replace(f'url(#{ident})',f'url(#{letter}_{ident})')
            raw=raw.replace(f'href="#{ident}"',f'href="#{letter}_{ident}"')
        group=ET.SubElement(svg,ns+"g",{"transform":f"translate({x*PT},{(h-y-ph)*PT})"})
        for element in ET.fromstring(raw): group.append(element)
    doc.save(out/f"{STEM}.pdf",garbage=4,deflate=True)
    page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),alpha=False).save(out/f"{STEM}.png")
    ET.ElementTree(svg).write(out/f"{STEM}.svg",encoding="utf-8",xml_declaration=True)
    (REV/"placement.json").write_text(json.dumps({"unit":"mm","origin":"lower_left","canvas":CANVAS,
        "panels":[dict(zip(("letter","x","y","width","height"),p)) for p in PANELS]},indent=2)+"\n")
    manifest={"schema_version":1,"figure":{"width_pt":w*PT,"height_pt":h*PT},
        "panels":[{"id":p[0],"bbox_pt":[p[1]*PT,p[2]*PT,(p[1]+p[3])*PT,(p[2]+p[4])*PT]} for p in PANELS],
        "row_groups":[{"id":"positive","panels":list("abc")},{"id":"negative","panels":list("def")}],
        "column_groups":[{"id":"total","panels":["a","d"]},{"id":"cross","panels":["b","e"]},
                         {"id":"coverage","panels":["c","f"]}],
        "exemptions":[{"panels":list("ghi"),"checks":["row","column"],
            "reason":"Local crop aspects differ; deliberate wide P29 detail plus two narrower coverage details. No scale comparison implied."}]}
    (REV/"alignment_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(f"Assembled {w} x {h} mm; no panel scaling.")

if __name__=="__main__": main()
