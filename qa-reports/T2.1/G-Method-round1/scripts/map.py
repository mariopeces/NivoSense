import sys, math, io, urllib.request, geopandas as gpd, shapely, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image
pr, dl, out = sys.argv[1:4]
W=3857
r = gpd.read_file(f"{dl}/rediam_eennpp.gml")
pnat = r[(r.NOMBRE.str.upper()=="SIERRA NEVADA")&(r.FIGURA=="Parque Natural")].to_crs(W)
e = gpd.read_file(f"zip://{dl}/Enp2025_shp.zip!Enp2025_shp/Enp2025_p.shp")
pnac = e[(e.SITE_NAME=="Sierra Nevada")&(e.ODESIGNATE=="Parque Nacional")].to_crs(W)
d = gpd.read_file(f"{pr}/data/domain.geojson").to_crs(W)
b = gpd.read_file(f"{pr}/data/basins.geojson").to_crs(W)
def tiles(ax, bounds, z):
    R=6378137*math.pi
    def t(x,y): return int((x+R)/(2*R)*2**z), int((R-y)/(2*R)*2**z)
    x0,y1=t(bounds[0],bounds[1]); x1,y0=t(bounds[2],bounds[3])
    img=Image.new("RGB",((x1-x0+1)*256,(y1-y0+1)*256))
    for x in range(x0,x1+1):
        for y in range(y0,y1+1):
            req=urllib.request.Request(f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",headers={"User-Agent":"NivoSense QA"})
            img.paste(Image.open(io.BytesIO(urllib.request.urlopen(req,timeout=30).read())).convert("RGB"),((x-x0)*256,(y-y0)*256))
    s=2*R/2**z
    ax.imshow(img,extent=(-R+x0*s,-R+(x1+1)*s,R-(y1+1)*s,R-y0*s),zorder=0)
cols={508678:"#4c78a8",604361:"#f58518",604370:"#54a24b",604456:"#b279a2"}
def draw(ax,bounds,z,title):
    tiles(ax,bounds,z)
    for _,row in b.iterrows():
        gpd.GeoSeries([row.geometry],crs=W).plot(ax=ax,color=cols[row.cod_uni],alpha=.35,edgecolor=cols[row.cod_uni],linewidth=.8,zorder=1)
    pnat.boundary.plot(ax=ax,color="#2e7d32",linewidth=1.4,zorder=2)
    pnac.boundary.plot(ax=ax,color="#c62828",linewidth=1.4,zorder=3)
    d[d.part=="domain"].boundary.plot(ax=ax,color="k",linewidth=.9,linestyle="--",zorder=4)
    ax.set_xlim(bounds[0],bounds[2]); ax.set_ylim(bounds[1],bounds[3]); ax.set_title(title,fontsize=9); ax.set_xticks([]); ax.set_yticks([])
fig,ax=plt.subplots(figsize=(14,7),dpi=130)
bb=d.total_bounds; pad=4000
draw(ax,(bb[0]-pad,bb[1]-pad,bb[2]+pad,bb[3]+pad),10,"T2.1 G-Method: red = PNac (MITECO ENP 2025, own fetch), green = PNat (REDIAM WFS, own fetch), black dashed = PR domain; fills = PR sub-basins (blue 508678, orange 604361, green 604370, purple 604456)")
fig.savefig(f"{out}/map_overview.png",bbox_inches="tight"); plt.close(fig)
# zooms: tiny basin parts
zooms=[]
for _,row in b.iterrows():
    for p in shapely.get_parts(row.geometry):
        if p.area/ (math.cos(math.radians(37))**2) < 2e4: zooms.append((row.cod_uni,p))
print("tiny parts", len(zooms))
n=min(len(zooms),6)
if n:
    fig,axs=plt.subplots(1,n,figsize=(4*n,4),dpi=130)
    axs=[axs] if n==1 else axs
    for ax,(c,p) in zip(axs,zooms[:n]):
        cx,cy=p.centroid.x,p.centroid.y; h=600
        draw(ax,(cx-h,cy-h,cx+h,cy+h),16,f"{c} part {p.area*(math.cos(math.radians(37))**2):.0f} m2")
        gpd.GeoSeries([p],crs=W).boundary.plot(ax=ax,color="magenta",linewidth=2,zorder=5)
    fig.savefig(f"{out}/map_tiny_parts.png",bbox_inches="tight"); plt.close(fig)
# zoom at park contact (PNac/PNat junction) to look for gaps
inter = shapely.intersection(pnac.geometry.iloc[0].boundary, pnat.geometry.union_all().buffer(5))
pts=[inter.interpolate(f,normalized=True) for f in (0.1,0.4,0.7)]
fig,axs=plt.subplots(1,3,figsize=(12,4),dpi=130)
for ax,p in zip(axs,pts):
    h=300; draw(ax,(p.x-h,p.y-h,p.x+h,p.y+h),16,"PNac/PNat shared edge")
fig.savefig(f"{out}/map_shared_edge.png",bbox_inches="tight"); plt.close(fig)
