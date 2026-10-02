"""Panel c: unchanged first activation by year, at native 83 × 68 mm."""
from fig2_data import load,TARGETS
from fig2_style import *

def main():
    cities,tracks,base,current,additions=load()
    target=cities[cities.gba_city.isin(TARGETS)]
    fig=plt.figure(figsize=(83*MM,68*MM));ax=axes_mm(fig,1,13,81,49)
    target.plot(ax=ax,facecolor='#F7F7F7',edgecolor=INK,linewidth=.55)
    base.plot(ax=ax,color='#D9D9D9',linewidth=.42)
    for year in YEARS:
        additions[additions.first_active_year.eq(year)].plot(ax=ax,color=YEARS[year],linewidth=.95,linestyle=STYLES[year])
    limits(ax,target.total_bounds);tri_city_labels(ax,cities,tracks)
    heading(fig,'c','2018–2024 activations');year_legend(fig)
    export(fig,'fig2c_activations')

if __name__=='__main__': main()
