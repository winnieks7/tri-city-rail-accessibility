"""Native-print vector style for the three Figure 1 panels."""
import json
import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch
from matplotlib.path import Path
from figure_style_kernel import apply_figure_style
from fig1_content import REV

apply_figure_style(frame="open",font="Arial",sizes=(7,6.5,6),grid=False)
mpl.rcParams.update({"font.family":"Arial","font.size":7,"pdf.fonttype":42,"svg.fonttype":"none",
    "figure.dpi":300,"savefig.dpi":600,"savefig.bbox":None,"svg.hashsalt":"land-figure1-concept-20261002"})
INK="#25333B"; MUTED="#617078"; PRIOR="#B6BEC3"; BLUE="#0072B2"; ORANGE="#B76B22"
POP="#C47448"; POP_EDGE="#874D31"; VIOLET="#8C6BB1"

def canvas(w=53,h=74):
    fig=plt.figure(figsize=(w/25.4,h/25.4)); ax=fig.add_axes([0,0,1,1])
    ax.set(xlim=(0,w),ylim=(0,h)); ax.set_axis_off()
    return fig,ax

def text(ax,x,y,s,size=6.5,**kwargs):
    return ax.text(x,y,s,fontsize=size,color=INK,va="top",**kwargs)

def heading(ax,letter,label):
    top=ax.get_ylim()[1]-1.5
    text(ax,0,top,letter,size=8,weight="bold")
    text(ax,4,top-.2,label,size=7)

def arrow(ax,points,color=MUTED,linestyle="-"):
    p=Path(points,[Path.MOVETO]+[Path.LINETO]*(len(points)-1))
    ax.add_patch(FancyArrowPatch(path=p,arrowstyle="-|>",mutation_scale=6,
                               linewidth=.7,color=color,linestyle=linestyle,clip_on=False))

def save(fig,name):
    out=REV/"panels"; out.mkdir(parents=True,exist_ok=True); fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    labels=[t for t in fig.findobj(mpl.text.Text) if t.get_visible() and t.get_text().strip()]
    collisions=[]
    for i,t in enumerate(labels):
        box=mpl.text.Text.get_window_extent(t,renderer)
        assert fig.bbox.contains(box.x0,box.y0) and fig.bbox.contains(box.x1,box.y1),(name,t.get_text(),"clipped")
        for u in labels[i+1:]:
            if box.overlaps(mpl.text.Text.get_window_extent(u,renderer)):
                collisions.append([t.get_text(),u.get_text()])
    (out/f"{name}_text_checks.json").write_text(json.dumps({"text_pairs":collisions},indent=2))
    assert not collisions,(name,collisions)
    for ext in ["pdf","svg","png"]: fig.savefig(out/f"{name}.{ext}",dpi=600)
    plt.close(fig)
