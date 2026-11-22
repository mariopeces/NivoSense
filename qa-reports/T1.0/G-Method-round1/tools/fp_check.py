import json, sys, urllib.request
import rasterio
from shapely.geometry import shape, Point
from pyproj import Transformer
from make_chips import ENV, item
pts = json.load(open(sys.argv[1], encoding="utf-8"))["features"]
bad = sys.argv[2].split(",")
blind = {f["properties"]["id"] for f in json.load(open("blind_points.geojson"))["features"]}
tr = Transformer.from_crs(4326, 32630, always_xy=True)
for f in pts:
    p = f["properties"]
    if p["id"] not in bad: continue
    it = item(p["chip_scene_id"], "cache")
    fp = shape(it["geometry"])
    pt = Point(f["geometry"]["coordinates"])
    # distance in metres to the footprint
    from shapely.ops import transform
    d = transform(lambda x, y, z=None: tr.transform(x, y), fp).exterior.distance(Point(p["x"], p["y"]))
    vals = []
    with rasterio.Env(**ENV):
        for b in ("red", "swir16"):
            with rasterio.open("/vsis3/" + it["assets"][b]["href"][5:]) as ds:
                vals.append(int(next(ds.sample([(p["x"], p["y"])]))[0]))
    print(p["id"], p["chip_scene_id"], f"dist_to_footprint_m={d:.0f}", "raw B04,B11 at point:", vals, "in G-Method blind subset" if p["id"] in blind else "")
