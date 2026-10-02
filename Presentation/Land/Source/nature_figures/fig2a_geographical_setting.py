"""Panel a: full GBA context and a coastal locator, at native 173 × 84 mm."""
import geopandas as gpd
from shapely.geometry import box, Point
from matplotlib.patches import Patch, Rectangle, ConnectionPatch
from matplotlib.lines import Line2D
from matplotlib.font_manager import FontProperties
from fig2_data import INPUTS, CRS, REGION_LONLAT, TARGETS, load
from fig2_style import *

def main():
    cities,tracks,base,current,additions=load()
    fig=plt.figure(figsize=(173*MM,84*MM))
    ax=axes_mm(fig,1,2,112,76)
    ax.set_facecolor(SEA)
    regional=gpd.GeoSeries([box(*REGION_LONLAT)],crs=4326).to_crs(CRS).total_bounds
    gadm=gpd.read_file(INPUTS['gadm'])
    land=gadm.to_crs(CRS).clip(box(*regional))
    land.plot(ax=ax,facecolor='#F4F4F3',edgecolor='none',linewidth=0)
    cities.plot(ax=ax,facecolor=INVENTORY,edgecolor='white',linewidth=.45)
    cities[cities.gba_city.isin(['Hong Kong','Macao'])].plot(ax=ax,facecolor=CONTEXT,edgecolor='white',linewidth=.35)
    cities[cities.gba_city.isin(['Huizhou','Zhaoqing'])].plot(ax=ax,facecolor=DEST,edgecolor='white',linewidth=.45)
    cities[cities.gba_city.isin(TARGETS)].plot(ax=ax,facecolor=ORIGIN,edgecolor='#496373',linewidth=.65)
    current.plot(ax=ax,color=BLUE,linewidth=.35,zorder=4)
    limits(ax,regional,pad=0)
    fig.canvas.draw()
    # Fixed geographic labels; leaders end at municipality interior points.
    labels={'Zhaoqing':(112.00,23.66),'Guangzhou':(113.60,24.27),'Foshan':(111.92,22.92),
            'Dongguan':(114.42,23.43),'Huizhou':(114.87,23.78),'Shenzhen':(115.20,22.40),
            'Zhongshan':(111.78,22.50),'Jiangmen':(112.52,22.12),'Zhuhai':(112.22,21.42),
            'Hong Kong':(114.86,22.18),'Macao':(113.02,21.52)}
    for row in cities.itertuples():
        point=row.geometry.representative_point()
        pos=gpd.GeoSeries([Point(*labels[row.gba_city])],crs=4326).to_crs(CRS).iloc[0]
        if row.gba_city=='Dongguan':
            # Place the full name in nearby clear space, retaining a leader to
            # Dongguan itself. Search geometry, not guessed pixel offsets.
            renderer=fig.canvas.get_renderer()
            tw,th,_=renderer.get_text_width_height_descent('Dongguan',FontProperties(family='Arial',size=7),False)
            origin=ax.transData.transform((pos.x,pos.y))
            pad=3
            d0=ax.transData.inverted().transform(origin-np.array([tw/2+pad,th/2+pad]))
            d1=ax.transData.inverted().transform(origin+np.array([tw/2+pad,th/2+pad]))
            hw,hh=(d1-d0)/2
            boundaries=cities.boundary
            candidates=[]
            for dx in range(-30000,30001,2000):
                for dy in range(-30000,30001,2000):
                    rect=box(pos.x+dx-hw,pos.y+dy-hh,pos.x+dx+hw,pos.y+dy+hh)
                    if not boundaries.intersects(rect).any() and not len(current.sindex.query(rect,predicate='intersects')):
                        candidates.append((dx*dx+dy*dy,pos.x+dx,pos.y+dy))
            assert candidates
            _,xx,yy=min(candidates)
            pos=Point(xx,yy)
        callout=row.gba_city in ['Guangzhou','Foshan','Dongguan','Hong Kong','Macao','Zhuhai','Zhongshan','Shenzhen']
        ax.annotate(row.gba_city,(point.x,point.y),xytext=(pos.x,pos.y),textcoords='data',
            ha='center',va='center',fontsize=7 if row.gba_city in TARGETS else 6.5,
            color='#173B4D' if row.gba_city in TARGETS else '#41484C',
            arrowprops={'arrowstyle':'-','lw':.45,'color':'#63717A','shrinkA':3,'shrinkB':1} if callout else None,
            zorder=10)
    water=gpd.GeoSeries([Point(113.72,22.35),Point(114.35,21.70)],crs=4326).to_crs(CRS)
    ax.annotate('Pearl River\nestuary',(water.iloc[0].x,water.iloc[0].y),
        xytext=(water.iloc[1].x,water.iloc[1].y),ha='center',va='center',fontsize=6.5,
        color='#547482',fontstyle='italic',arrowprops={'arrowstyle':'-','lw':.45,'color':'#8199A4','shrinkA':3})
    scale_bar(ax,50,xy=(.04,.08)); north(ax,xy=(.96,.90))
    heading(fig,'a','Greater Bay Area and the three-city study area')

    inset=axes_mm(fig,119,37,52,40)
    coast=gpd.read_file('zip://'+str(INPUTS['land'])).clip(box(75,10,140,55))
    # A physical locator avoids introducing unrelated national boundary claims.
    coast.plot(ax=inset,facecolor='#E8EBEB',edgecolor='#AFB8BD',linewidth=.3)
    gd=gadm[gadm.NAME_1.eq('Guangdong')].dissolve()
    gd.plot(ax=inset,facecolor='#A8CDDF',edgecolor='#4A7389',linewidth=.5)
    limits(inset,(75,10,140,55),pad=0)
    inset.set_aspect(1/np.cos(np.deg2rad(32)))
    inset.set_facecolor(SEA)
    for s in inset.spines.values(): s.set_visible(True);s.set_linewidth(.4);s.set_color('#D6DDE0')
    inset.text(103,37,'China',fontsize=7,ha='center',color=INK)
    inset.annotate('Guangdong',(113.4,24),xytext=(98,28),ha='center',fontsize=6.5,
                   arrowprops={'arrowstyle':'-','lw':.5,'color':INK})
    x0,y0,x1,y1=REGION_LONLAT
    inset.add_patch(Rectangle((x0,y0),x1-x0,y1-y0,fill=False,ec=BLUE,lw=.9))
    fig.add_artist(ConnectionPatch(xyA=(x0,y0),coordsA=inset.transData,
        xyB=(1,.46),coordsB=ax.transAxes,color='#9AAAB2',linewidth=.45,zorder=15))
    handles=[Patch(fc=ORIGIN,ec='#496373',lw=.5,label='Three-city origins'),
             Patch(fc=DEST,ec='none',label='Other destination cities'),
             Patch(fc=INVENTORY,ec='none',label='Other inventory cities'),
             Patch(fc=CONTEXT,ec='none',label='Hong Kong and Macao'),
             Line2D([0],[0],color=BLUE,lw=.7,label='2024 modelled rail')]
    fig.legend(handles=handles,loc='lower left',bbox_to_anchor=(119/173,3/84),
               frameon=False,fontsize=6.5,labelspacing=.65,handlelength=1.3,borderaxespad=0)
    export(fig,'fig2a_geographical_setting')

if __name__=='__main__': main()
