"""Shared cartographic primitives; all dimensions are final-print dimensions."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.transforms import Bbox
import numpy as np
from shapely.geometry import box
from figure_style_kernel import apply_figure_style
from fig2_data import OUT

apply_figure_style(frame='open',font='Arial',sizes=(7,6.5,6),grid=False)
plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial'],
    'pdf.fonttype':42,'svg.fonttype':'none','font.size':7,'figure.dpi':300,
    'savefig.dpi':450,'savefig.bbox':None,'svg.hashsalt':'land-geography-20261002'})
MM=1/25.4
BLUE='#0072B2'
INK='#333333'
SEA='#F0F6F8'
ORIGIN='#CFE8F3'
DEST='#E1EED9'
INVENTORY='#E6E8E9'
CONTEXT='#BFC6CA'
YEARS={2018:'#0072B2',2019:'#009E73',2020:'#D55E00',2021:'#CC79A7',2022:'#56B4E9',2023:'#A45A00',2024:'#111111'}
STYLES={2018:'solid',2019:(0,(5,1.5)),2020:(0,(1.2,1.2)),2021:(0,(5,1.2,1.2,1.2)),2022:(0,(3,1.2)),2023:(0,(2,1.1,1,1.1)),2024:(0,(7,1.4))}

def axes_mm(fig,x,y,w,h):
    fw,fh=fig.get_size_inches()/MM
    return fig.add_axes([x/fw,y/fh,w/fw,h/fh])

def limits(ax,bounds,pad=.035):
    x0,y0,x1,y1=bounds
    ax.set(xlim=(x0-pad*(x1-x0),x1+pad*(x1-x0)),ylim=(y0-pad*(y1-y0),y1+pad*(y1-y0)))
    ax.set_aspect('equal'); ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_visible(False)

def heading(fig,letter,title,x=1,y=None):
    w,h=fig.get_size_inches()/MM
    y=h-2 if y is None else y
    fig.text(x/w,y/h,letter,fontsize=8,fontweight='bold',va='top')
    fig.text((x+5)/w,y/h,title,fontsize=7,va='top')

def scale_bar(ax,km=50,xy=(.06,.07)):
    x0,x1=ax.get_xlim(); y0,y1=ax.get_ylim()
    x=x0+xy[0]*(x1-x0); y=y0+xy[1]*(y1-y0)
    ax.plot([x,x+km*1000],[y,y],color=INK,lw=1.2,solid_capstyle='butt')
    ax.text(x+km*500,y+.026*(y1-y0),f'{km} km',ha='center',va='bottom',fontsize=6)

def north(ax,xy=(.96,.89)):
    ax.annotate('',xy,xytext=(xy[0],xy[1]-.10),xycoords='axes fraction',
                arrowprops={'arrowstyle':'-|>','lw':.65,'color':INK})
    ax.text(xy[0],xy[1]+.015,'N',transform=ax.transAxes,ha='center',fontsize=6)

def tri_city_labels(ax,cities,tracks):
    names={'Guangzhou':'GZ','Foshan':'FS','Dongguan':'DG'}
    for row in cities[cities.gba_city.isin(names)].itertuples():
        x0,y0,x1,y1=row.geometry.bounds; center=row.geometry.representative_point()
        choices=[]
        for x in np.arange(x0,x1,4000):
            for y in np.arange(y0,y1,4000):
                rect=box(x-7500,y-5000,x+7500,y+5000)
                if row.geometry.contains(rect) and not len(tracks.sindex.query(rect,predicate='intersects')): choices.append((x,y))
        assert choices
        x,y=min(choices,key=lambda q:(q[0]-center.x)**2+(q[1]-center.y)**2)
        ax.text(x,y,names[row.gba_city],ha='center',va='center',fontsize=6.5,
                bbox={'facecolor':'white','edgecolor':'none','pad':.7},zorder=20)

def year_legend(fig):
    handles=[Line2D([0],[0],color='#D9D9D9',lw=1.4,label='2017 network')]
    handles += [Line2D([0],[0],color=YEARS[y],lw=1.4,ls=STYLES[y],label=str(y)) for y in YEARS]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.005),
               ncol=4,frameon=False,fontsize=6,handlelength=1.6,columnspacing=.65,labelspacing=.5)

def export(fig,name):
    OUT.mkdir(parents=True,exist_ok=True)
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    texts=[t for t in fig.findobj(matplotlib.text.Text) if t.get_visible() and t.get_text().strip()]
    collisions=[]
    for i,t in enumerate(texts):
        # Annotation's default bbox also includes its leader, which is not text.
        b=matplotlib.text.Text.get_window_extent(t,renderer)
        assert fig.bbox.contains(b.x0,b.y0) and fig.bbox.contains(b.x1,b.y1), (name,t.get_text(),'clipped')
        for u in texts[i+1:]:
            if b.overlaps(matplotlib.text.Text.get_window_extent(u,renderer)): collisions.append([t.get_text(),u.get_text()])
    (OUT/f'{name}_text_checks.json').write_text(json.dumps({'text_pairs':collisions},indent=2))
    for ext in ('pdf','svg','png'): fig.savefig(OUT/f'{name}.{ext}')
    plt.close(fig)
