"""A two-event coalition diamond explains averaging over alternative orders."""
from fig1_style import canvas,heading,text,save,arrow,PRIOR,BLUE,VIOLET,INK
from fig1_content import NODES,PRIOR_EDGES,EVENT_EDGES

def network(ax,x,y,events):
    scale=.75
    for a,b in PRIOR_EDGES:
        ax.plot([x+scale*NODES[a][0],x+scale*NODES[b][0]],
                [y+scale*NODES[a][1],y+scale*NODES[b][1]],color=PRIOR,lw=1.0,zorder=2)
    for event in events:
        for a,b in EVENT_EDGES[event]:
            ax.plot([x+scale*NODES[a][0],x+scale*NODES[b][0]],
                    [y+scale*NODES[a][1],y+scale*NODES[b][1]],
                    color=BLUE if event=="A" else VIOLET,lw=1.2,
                    ls="-" if event=="A" else (0,(2.5,1.5)),zorder=3)
    ax.scatter([x+scale*p[0] for p in NODES],[y+scale*p[1] for p in NODES],s=7,
               facecolors="white",edgecolors=INK,linewidths=.5,zorder=4)

def main():
    fig,ax=canvas(112,50); heading(ax,"d","Within-year event attribution")
    states=[("Prior year-end",(),2,20),("A only",("A",),35,30),
            ("B only",("B",),35,10),("A + B",("A","B"),68,20)]
    for label,events,x,y in states:
        text(ax,x-1,y+11.5,label,size=6.5); network(ax,x,y,events)
    for points,color in [([(17,24),(31,33)],BLUE), ([(17,23),(31,15)],VIOLET),
                         ([(50,33),(64,25)],VIOLET), ([(50,15),(64,23)],BLUE)]:
        arrow(ax,points,color=color,linestyle="-" if color==BLUE else (0,(2.5,1.5)))
    for y,color,label,ls in [(34,BLUE,"Event A","-"),(27,VIOLET,"Event B",(0,(2.5,1.5)))]:
        ax.plot([86,90],[y,y],color=color,lw=1.1,ls=ls)
        text(ax,92,y+1.2,label,size=6)
    text(ax,85,20,"Two-event\nexample",size=6)
    text(ax,0,5,"Exact Shapley: average marginal change across event orders",size=6.5)
    save(fig,"fig1d_allocation")
if __name__=="__main__": main()
