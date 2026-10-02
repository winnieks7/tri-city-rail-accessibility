"""Walking access is a network threshold, not a circular station buffer."""
from fig1_style import canvas,heading,text,save
from fig1_spatial import spatial_scene
def main():
    fig,ax=canvas(55,59); heading(ax,"a","Station-access coverage")
    text(ax,0,51,"Walk to an active station",size=6.5)
    spatial_scene(ax,"coverage"); save(fig,"fig1a_coverage")
if __name__=="__main__": main()
