"""Result-only loaders and native-size maps for manuscript Figure 5."""
from functools import lru_cache
import hashlib
import json
import geopandas as gpd
import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
from fig5_content import METRICS,TITLES,EXPECTED,NAMES,OWNING_SECTION,STEM,CANVAS
from transport_figure_common import (
    ROOT,LAND,CONTRIBUTION,GRID,CITIES,ANNUAL,DIVERGING,load_grid_and_boundaries,
    load_missing_origin_grid,raster_spec,rasterize,values_on_grid,event_code_map,
    signed_norm,signed_colorbar_ticks,format_map_axis,mark_missing_origins,
    plot_event_topology_change,event_topology_change,event_topology_legend_handles,
    add_scale_bar,add_north_arrow,apply_figure_style)
from Codes.analysis.transport_event_state import FrozenEventStateBuilder

REV=LAND/"Generated/figure5"
PANEL_DIR=REV/"panels"
SUMMARY=ROOT/"Results/tables/transport_d_project_summary.csv"
BASELINE_VALUES=LAND/"ReferenceValues"/f"{STEM}.json"
BOUNDARY="#90979B"
apply_figure_style(frame="open",font="Arial",sizes=(7,6.5,6),grid=False)
mpl.rcParams.update({"pdf.fonttype":42,"svg.fonttype":"none","savefig.bbox":None,
    "svg.hashsalt":"transport-d-figure5-20261002","figure.dpi":300,"savefig.dpi":450,
    "font.family":"Arial","font.size":7})

@lru_cache(maxsize=1)
def load_data():
    """Read retained outcomes; no routing or Shapley computations."""
    grid,cities=load_grid_and_boundaries(valid_only=True)
    missing=load_missing_origin_grid()
    assert len(grid)==50607 and len(missing)==265
    spec=raster_spec(grid); summary=pd.read_csv(SUMMARY); codes=event_code_map(summary)
    contributions=pd.read_parquet(CONTRIBUTION,columns=["grid_id","analysis_status","event_id",*METRICS])
    contributions=contributions.loc[contributions.analysis_status.ne("missing_walk_snap")]
    builder=FrozenEventStateBuilder(); change_cache={}; panels={}; records=[]; source_rows=[]
    for col,(metric,aggregate) in enumerate(METRICS.items()):
        events=[summary.loc[summary[aggregate].idxmax()],summary.loc[summary[aggregate].idxmin()]]
        selected=contributions.loc[contributions.event_id.isin([x.event_id for x in events]),metric]
        norm,limit,linthresh=signed_norm(selected.to_numpy(),percentile=99.5)
        for row,event in enumerate(events):
            letter="abcdef"[row*3+col]; code=codes[event.event_id]
            assert code==EXPECTED[letter]
            frame=contributions.loc[contributions.event_id.eq(event.event_id),["grid_id",metric]]
            values=values_on_grid(grid,frame,metric)
            assert np.isfinite(values).all() and len(frame)==len(grid)
            if event.event_id not in change_cache:
                # Geometry-only singleton/empty comparison, not outcome evaluation.
                change_cache[event.event_id]=event_topology_change(builder,event.event_id,grid.crs)
            panels[letter]=dict(code=code,metric=metric,norm=norm,values=values,
                change=change_cache[event.event_id],column=col)
            records.append(dict(panel=letter,selection="largest_positive" if row==0 else "most_negative",
                metric=metric,event_id=event.event_id,event_code=code,year=int(event.year),event_label=event.event_label,
                equal_city_population_weighted_contribution=float(event[aggregate]),
                absolute_colour_limit=limit,linear_threshold=linthresh))
            source_rows.append(pd.DataFrame({"panel":letter,"grid_id":grid.grid_id,
                "event_code":code,"metric":metric,"value":values,"owning_section":OWNING_SECTION}))
    negative=panels["a"]["values"] < -1e-10
    assert negative.sum()==28
    bounds={"g":(grid.loc[negative].total_bounds+[-2000,-2000,2000,3500]).tolist()}
    for detail,parent in [("h","c"),("i","f")]:
        active=np.abs(panels[parent]["values"])>1e-10
        bounds[detail]=(grid.loc[active].total_bounds+[-1500,-1500,1500,1500]).tolist()
    stops_path=ROOT/"Data/interim/transport/d_route_stop_sequence_candidates.parquet"
    stops=gpd.read_parquet(stops_path).to_crs(grid.crs); labelled=[]
    for name,label in [("枫下","Fengxia"),("镇龙","Zhenlong"),("中新","Zhongxin"),("增城广场","Zengcheng Square")]:
        point=stops.loc[stops.station_name.eq(name)].iloc[0].geometry
        labelled.append(dict(station_name=name,label=label,x=point.x,y=point.y))
    prior=json.loads(BASELINE_VALUES.read_text())
    assert records==prior["panels"],"Panel selection or scale changed"
    detail_record=dict(negative_cells=int(negative.sum()),bounds_m=bounds["g"],
        all_signs_retained=True,normalization_shared_with_parent=True,stations=labelled)
    assert detail_record==prior["local_enlargement"],"P29 detail changed"
    REV.mkdir(parents=True,exist_ok=True)
    (REV/"values.json").write_text(json.dumps(prior,indent=2)+"\n")
    pd.concat(source_rows,ignore_index=True).to_csv(REV/"source_data.csv.gz",index=False,compression="gzip")
    missing[["grid_id"]].assign(status="missing_walk_snap",owning_section=OWNING_SECTION).to_csv(REV/"excluded_origins.csv",index=False)
    source_files=[GRID,CITIES,ANNUAL,CONTRIBUTION,SUMMARY,stops_path]
    manifest={"inputs":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
        "panel_values_identical_to_previous":True,"valid_origins":len(grid),"excluded_origins":len(missing),
        "research_runs_executed":0,"detail_bounds_m":bounds,"detail_parent":{"g":"a","h":"c","i":"f"},
        "source_data_rows":6*len(grid)}
    (REV/"input_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return dict(grid=grid,cities=cities,missing=missing,spec=spec,panels=panels,bounds=bounds,stations=labelled)

def figure(w,h): return plt.figure(figsize=(w/25.4,h/25.4))

def save_panel(fig,name):
    PANEL_DIR.mkdir(parents=True,exist_ok=True); fig.canvas.draw()
    for ext in ["pdf","svg","png"]: fig.savefig(PANEL_DIR/f"{name}.{ext}",dpi=450)
    plt.close(fig)

def title(fig,letter,text,width):
    fig.text(0,.98,letter,ha="left",va="top",fontsize=8,weight="bold")
    fig.text(3.7/width,.976,text,ha="left",va="top",fontsize=6.5)

def render_map(letter):
    data=load_data(); info=data["panels"][letter]; fig=figure(57,46)
    ax=fig.add_axes([0,0,1,40.5/46])
    ax.imshow(rasterize(data["grid"],info["values"],data["spec"]),origin="lower",extent=data["spec"]["extent"],
        cmap=DIVERGING,norm=info["norm"],interpolation="nearest",rasterized=True)
    format_map_axis(ax,data["cities"],data["spec"],city_labels=letter=="a",boundary_color=BOUNDARY)
    plot_event_topology_change(ax,info["change"],linewidth=.45,show_stops=info["column"]!=2)
    mark_missing_origins(ax,data["missing"])
    title(fig,letter,f'{info["code"]} · {NAMES[info["code"]]}',57)
    if letter=="a":
        for text in ax.texts:
            if text.get_text()=="GZ": text.set_position((15000,85000))
        add_scale_bar(ax,data["spec"]); add_north_arrow(ax)
    detail={"a":"g","c":"h","f":"i"}.get(letter)
    if detail:
        xmin,ymin,xmax,ymax=data["bounds"][detail]
        ax.add_patch(Rectangle((xmin,ymin),xmax-xmin,ymax-ymin,fill=False,ec="#555B60",lw=.65,zorder=29))
        # Matching letters and a short local leader replace cross-sheet connectors.
        ax.annotate(detail,(xmin,ymax),xytext=(-7,6),textcoords="offset points",ha="right",va="bottom",
            fontsize=6.5,weight="bold",color="#454B50",zorder=30,
            arrowprops={"arrowstyle":"-","lw":.45,"color":"#555B60","shrinkA":1,"shrinkB":0})
    save_panel(fig,f"fig5{letter}")

def render_detail(letter):
    data=load_data(); parent={"g":"a","h":"c","i":"f"}[letter]; info=data["panels"][parent]
    width={"g":108,"h":40,"i":23}[letter]; fig=figure(width,49)
    ax=fig.add_axes([0,1/49,1,42/49] if letter=="g" else [0,4/49,1,39/49])
    ax.imshow(rasterize(data["grid"],info["values"],data["spec"]),origin="lower",extent=data["spec"]["extent"],
        cmap=DIVERGING,norm=info["norm"],interpolation="nearest",rasterized=True)
    xmin,ymin,xmax,ymax=data["bounds"][letter]
    boundaries=data["cities"].boundary.clip((xmin,ymin,xmax,ymax))
    if not boundaries.empty: boundaries.plot(ax=ax,color=BOUNDARY,lw=.35)
    mark_missing_origins(ax,data["missing"])
    ax.set(xlim=(xmin,xmax),ylim=(ymin,ymax),xticks=[],yticks=[]); ax.set_aspect("equal")
    for spine in ax.spines.values():
        spine.set_visible(True); spine.set_linewidth(.45); spine.set_color("#B8BEC1")
    if letter=="g":
        title(fig,letter,"P29 · Northeastern Guangzhou",width)
        for station,(dx,dy) in zip(data["stations"],[(10,10),(-5,-13),(9,13),(-25,11)]):
            x,y=station["x"],station["y"]
            ax.scatter([x],[y],s=12,facecolors="none",edgecolors="#222222",linewidths=.6,zorder=25)
            ax.annotate(station["label"],(x,y),xytext=(dx,dy),textcoords="offset points",ha="center",
                va="bottom" if dy>0 else "top",fontsize=6.5,color="#222222",zorder=26,
                arrowprops={"arrowstyle":"-","lw":.4,"color":"#555555","shrinkA":3,"shrinkB":3})
        sx,sy,length=xmax-8000,ymax-2200,5000
        ax.plot([sx,sx+length],[sy,sy],color="#333333",lw=.8)
        ax.text(sx+length/2,sy+600,"5 km",ha="center",va="bottom",fontsize=6.5)
    else:
        title(fig,letter,f'{info["code"]} · Coverage',width)
        length=5000 if letter=="h" else 2000
        fig.canvas.draw(); box=ax.get_position(); fraction=box.width*length/(xmax-xmin); start=box.x0
        fig.add_artist(Line2D([start,start+fraction],[1.2/49,1.2/49],transform=fig.transFigure,color="#333333",lw=.8))
        fig.text(start+fraction+.025,1.2/49,f"{length//1000} km",ha="left",va="center",fontsize=6)
    save_panel(fig,f"fig5{letter}")

def render_furniture():
    data=load_data(); w,h=CANVAS; fig=figure(w,h)
    for x,label in zip([31.5,91.5,151.5],TITLES):
        fig.text(x/w,199/h,label,ha="center",va="top",fontsize=7)
    for y,text in [(191,"Largest positive contribution"),(136,"Most negative contribution"),(69,"Local detail")]:
        fig.text(3/w,y/h,text,ha="left",va="bottom",fontsize=7,color="#30383D")
    for index,parent in enumerate("abc"):
        norm=data["panels"][parent]["norm"]
        cax=fig.add_axes([(7+60*index)/w,80/h,49/w,2/h])
        cb=fig.colorbar(mpl.cm.ScalarMappable(norm=norm,cmap=DIVERGING),cax=cax,orientation="horizontal")
        signed_colorbar_ticks(cb,norm); cb.ax.tick_params(labelsize=6,length=2,width=.45,pad=1.5)
        cb.outline.set_visible(False)
        cb.set_label("Effective population" if index<2 else "Fraction",fontsize=6.5,labelpad=1.5)
    handles=event_topology_legend_handles(); handles[-1].set_color(BOUNDARY)
    handles.append(Line2D([0],[0],marker="o",markersize=3,markerfacecolor="none",color="#222222",lw=0,label="Labelled station (g)"))
    fig.legend(handles=handles,loc="lower center",bbox_to_anchor=(.5,.012),ncol=4,frameon=False,
        fontsize=6,handlelength=1.8,handletextpad=.55,columnspacing=1.4,labelspacing=.6)
    save_panel(fig,"fig5_furniture")
