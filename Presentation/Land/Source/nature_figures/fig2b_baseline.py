"""Panel b: unchanged 2017 baseline, at native 83 × 68 mm."""
from fig2_data import load,TARGETS
from fig2_style import *

def main():
    cities,tracks,base,current,additions=load()
    target=cities[cities.gba_city.isin(TARGETS)]
    fig=plt.figure(figsize=(83*MM,68*MM)); ax=axes_mm(fig,1,13,81,49)
    target.plot(ax=ax,facecolor='#F7F7F7',edgecolor=INK,linewidth=.55)
    base.plot(ax=ax,color='#767676',linewidth=.55)
    limits(ax,target.total_bounds); tri_city_labels(ax,cities,tracks)
    scale_bar(ax,25,xy=(.06,.80));north(ax,xy=(.95,.91))
    heading(fig,'b','2017 baseline')
    export(fig,'fig2b_baseline')

if __name__=='__main__': main()
