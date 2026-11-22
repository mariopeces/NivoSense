import sys, json
sys.path.insert(0, sys.argv[1])
from backend import ingest_webcams as w
from shapely.geometry import shape, Point
from shapely.ops import transform
import pyproj
root=__import__("pathlib").Path(sys.argv[1])
cfg=json.loads((root/"backend/webcam_sources.json").read_text())
area=w.load_area(cfg["region"], root)
fc=json.loads((root/"data/domain.geojson").read_text())
print([ (f["properties"].get("part"), f["geometry"]["type"]) for f in fc["features"]])
geom=shape(next(f["geometry"] for f in fc["features"] if f["properties"].get("part")=="domain"))
tr=pyproj.Transformer.from_crs(4326,25830,always_xy=True).transform
g=transform(tr,geom)
feed=open(sys.argv[2],"rb").read()
cams=w.parse_datex_cameras(feed,w.BoxArea(-180,-90,180,90),"x","x")
mism=0; near=[]
for c in cams:
    p=Point(tr(c["longitude"],c["latitude"])); dist=g.distance(p)
    ind = dist<=2000; mine=area.contains(c["longitude"],c["latitude"])
    if dist<6000: near.append((round(dist),c["id"],mine))
    if ind!=mine: mism+=1; print("MISMATCH",c["id"],dist,mine)
print("cams",len(cams),"mismatches",mism)
for x in sorted(near): print(x)
