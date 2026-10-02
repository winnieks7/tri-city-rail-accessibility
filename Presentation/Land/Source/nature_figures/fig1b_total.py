"""Population destinations in both municipalities enter the total sum."""
from fig1_style import canvas,heading,text,save
from fig1_spatial import spatial_scene
def main():
    fig,ax=canvas(55,59); heading(ax,"b","Total opportunity")
    text(ax,0,51,"Reach population by rail",size=6.5)
    spatial_scene(ax,"total"); save(fig,"fig1b_total")
if __name__=="__main__": main()
