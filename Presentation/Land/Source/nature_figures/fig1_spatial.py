"""Shared schematic geometry makes the three accessibility definitions comparable."""
from matplotlib.patches import Polygon, Circle
from fig1_content import CITY_LEFT,CITY_RIGHT,CITY_BORDER,STATIONS,RAIL_EDGES,ORIGIN,ORIGIN_WALK,DESTINATIONS
from fig1_style import INK,MUTED,POP,POP_EDGE,text

def line(ax,points,**kwargs):
    ax.plot([p[0] for p in points],[p[1] for p in points],**kwargs)

def spatial_scene(ax,metric):
    for coords in [CITY_LEFT,CITY_RIGHT]:
        ax.add_patch(Polygon(coords,facecolor="#F2F4F3",edgecolor="none",zorder=0))
    line(ax,CITY_BORDER,color="#8A949A",lw=.6,ls=(0,(2,2)),zorder=1)
    text(ax,4,46,"Origin city",size=6)
    text(ax,34,46,"Other city",size=6)
    for a,b in RAIL_EDGES:
        line(ax,[STATIONS[a],STATIONS[b]],color="#67767E",lw=1.15,zorder=2)
    if metric != "coverage":
        for x,y,station,outside in DESTINATIONS:
            assert station != 1, "Destination must not be the boarding station-occurrence"
            line(ax,[STATIONS[station],(x,y)],color="#859399",lw=.7,ls=(0,(1,1.6)),zorder=2)
            included=metric=="total" or outside
            ax.add_patch(Circle((x,y),1.65,facecolor=POP if included else "white",
                               edgecolor=POP_EDGE if included else "#AEB7BB",lw=.65,zorder=5))
    line(ax,ORIGIN_WALK,color=INK,lw=1.15,ls=(0,(1,1.5)),zorder=4)
    ax.scatter([p[0] for p in STATIONS],[p[1] for p in STATIONS],s=10,
               facecolors="white",edgecolors=INK,linewidths=.7,zorder=6)
    ax.scatter([ORIGIN[0]],[ORIGIN[1]],marker="D",s=16,facecolors=INK,edgecolors="white",linewidths=.35,zorder=7)
    if metric == "coverage":
        # An actual path is highlighted, not a radius around the station.
        text(ax,2,10,"Station reached within 15 min")
        text(ax,2,5,"along the pedestrian network",size=6)
    elif metric == "total":
        text(ax,2,10,"Time-weighted population")
        text(ax,2,5,"all destinations",size=6)
    else:
        text(ax,2,10,"Time-weighted population outside city")
        text(ax,2,5,"Hollow: same-city destinations",size=6)
