"""Symbolic output types and aggregation; no invented effect values."""
from matplotlib.patches import Rectangle
from fig1_style import canvas,heading,text,save,INK,MUTED
def main():
    fig,ax=canvas(56,50); heading(ax,"e","Spatial interpretation")
    for x,sign in [(1,"+"),(7,"−")]:
        ax.add_patch(Rectangle((x,33),4.5,4.5,facecolor="#F2F4F3",edgecolor="none"))
        text(ax,x+2.25,37,sign,size=7,ha="center")
    text(ax,15,37,"Signed event footprints")
    text(ax,15,32,"Gains and losses",size=6)
    ax.scatter([2.5,6.5,10.5],[22]*3,s=12,facecolors="#A9B4B9",edgecolors=INK,linewidths=.5)
    ax.plot([2.5,2.5,10.5,10.5],[20,18.5,18.5,20],color=MUTED,lw=.6)
    text(ax,15,24,"City-to-region comparisons")
    text(ax,15,19,"Population-weighted; equal-city",size=6)
    ax.scatter([3,9],[8,8],marker="D",s=13,facecolors=[INK,"white"],edgecolors=INK,linewidths=.6)
    text(ax,15,11,"Covered / uncovered origins")
    text(ax,15,6,"At each event-year start",size=6)
    save(fig,"fig1e_outputs")
if __name__=="__main__": main()
