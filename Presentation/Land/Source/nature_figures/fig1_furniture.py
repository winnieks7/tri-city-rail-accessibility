"""Shared fixed-input band and dependency arrows, all at native print size."""
from matplotlib.patches import Circle
from fig1_style import canvas,text,arrow,save,MUTED,INK,POP,POP_EDGE

def main():
    fig,ax=canvas(183,139)
    y=72
    ax.scatter([5],[y],marker="D",s=15,facecolor=INK,edgecolor="white",linewidths=.3)
    text(ax,8,y+1.2,"Origin",size=6)
    ax.scatter([30],[y],s=10,facecolor="white",edgecolor=INK,linewidths=.7)
    text(ax,33,y+1.2,"Active station",size=6)
    ax.plot([59,64],[y,y],color=INK,lw=.8,ls=(0,(1,1.5)))
    text(ax,66,y+1.2,"Walking link",size=6)
    ax.plot([94,99],[y,y],color="#67767E",lw=1.1)
    text(ax,101,y+1.2,"Rail link",size=6)
    ax.add_patch(Circle((125,y),1.1,facecolor=POP,edgecolor=POP_EDGE,lw=.5))
    text(ax,128,y+1.2,"Population",size=6)
    ax.plot([155,160],[y,y],color="#8A949A",lw=.6,ls=(0,(2,2)))
    text(ax,162,y+1.2,"City boundary",size=6)
    ax.plot([3,180],[68,68],color="#DCE1E2",lw=.5)
    # Allocations, not the raw metric definitions, feed the interpretation stage.
    arrow(ax,[(116,40),(122,40)])
    ax.plot([3,180],[12,12],color="#DCE1E2",lw=.5)
    text(ax,3,8,"Held fixed",size=6.5)
    text(ax,23,8,"500-m origins · 2023 WorldPop · pedestrian network · speeds, waits and transfer penalties",size=6.5)
    save(fig,"fig1_furniture")

if __name__=="__main__": main()
