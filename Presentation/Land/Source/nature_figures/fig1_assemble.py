"""Assemble Figure 1 from its independently reviewed native-size panels."""
import json
import re
import xml.etree.ElementTree as ET
import fitz
from fig1_content import REV,CANVAS,PANELS,STEM,PANEL_NAMES
PT=72/25.4
NAMES=PANEL_NAMES

def main():
    out=REV/"rendered"; out.mkdir(exist_ok=True)
    w,h=CANVAS; doc=fitz.open(); page=doc.new_page(width=w*PT,height=h*PT)
    ET.register_namespace("","http://www.w3.org/2000/svg")
    ET.register_namespace("xlink","http://www.w3.org/1999/xlink")
    ns="{http://www.w3.org/2000/svg}"
    svg=ET.Element(ns+"svg",{"width":f"{w*PT}pt","height":f"{h*PT}pt","viewBox":f"0 0 {w*PT} {h*PT}","version":"1.1"})
    for letter,x,y,pw,ph in [("shared",0,0,w,h),*PANELS]:
        name=NAMES[letter]; src=fitz.open(REV/"panels"/f"{name}.pdf")
        assert abs(src[0].rect.width-pw*PT)<.01 and abs(src[0].rect.height-ph*PT)<.01
        page.show_pdf_page(fitz.Rect(x*PT,(h-y-ph)*PT,(x+pw)*PT,(h-y)*PT),src,0,keep_proportion=True)
        raw=(REV/"panels"/f"{name}.svg").read_text()
        for ident in sorted(set(re.findall(r'\bid="([^"]+)"',raw)),key=len,reverse=True):
            raw=raw.replace(f'id="{ident}"',f'id="{letter}_{ident}"').replace(f'url(#{ident})',f'url(#{letter}_{ident})').replace(f'href="#{ident}"',f'href="#{letter}_{ident}"')
        group=ET.SubElement(svg,ns+"g",{"transform":f"translate({x*PT},{(h-y-ph)*PT})"})
        for element in ET.fromstring(raw): group.append(element)
    doc.save(out/f"{STEM}.pdf",garbage=4,deflate=True)
    page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),alpha=False).save(out/f"{STEM}.png")
    ET.ElementTree(svg).write(out/f"{STEM}.svg",encoding="utf-8",xml_declaration=True)
    (REV/"placement.json").write_text(json.dumps({"unit":"mm","origin":"lower_left","canvas":CANVAS,
        "panels":[dict(zip(("letter","x","y","width","height"),p)) for p in PANELS]},indent=2)+"\n")
    manifest={"schema_version":1,"figure":{"width_pt":w*PT,"height_pt":h*PT},
        "panels":[{"id":p[0],"bbox_pt":[p[1]*PT,p[2]*PT,(p[1]+p[3])*PT,(p[2]+p[4])*PT]} for p in PANELS],
        "row_groups":[{"id":"metrics","panels":list("abc")},
                      {"id":"attribution-and-interpretation","panels":list("de")}],
        "column_groups":[]}
    (REV/"alignment_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(f"Assembled {w} x {h} mm with no panel scaling.")

if __name__=="__main__": main()
