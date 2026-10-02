"""The same sum restricted to population beyond the origin municipality."""
from fig1_style import canvas,heading,text,save
from fig1_spatial import spatial_scene
def main():
    fig,ax=canvas(55,59); heading(ax,"c","Cross-city opportunity")
    text(ax,0,51,"Reach beyond the city boundary",size=6.5)
    spatial_scene(ax,"cross"); save(fig,"fig1c_cross")
if __name__=="__main__": main()
