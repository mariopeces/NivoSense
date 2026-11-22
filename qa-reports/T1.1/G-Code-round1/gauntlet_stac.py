"""G-Code T1.1 r1: independent check. pystac-client GET-free search with a bbox, grouping by
datatake id, shapely footprint vs domain in UTM, SCL read per tile with rasterio windows from
bounds onto my own 20 m grid (origin from the domain bounds rounded to 60 m, so it is a
different lattice anchoring than the builder's 20 m snap; S2 20 m pixels are on the 60 m
lattice too). Writes gauntlet_stac.json."""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.windows import from_bounds
from pyproj import Transformer
from pystac_client import Client
from shapely.geometry import shape, mapping
from shapely.ops import transform as stransform, unary_union

domain_path, start, end, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
gj = json.loads(Path(domain_path).read_text(encoding="utf-8"))
dom_ll = unary_union([shape(f["geometry"]) for f in gj["features"]])
to_utm = Transformer.from_crs(4326, 32630, always_xy=True).transform
dom = stransform(to_utm, dom_ll)
minx, miny, maxx, maxy = dom.bounds
L, T = np.floor(minx / 60) * 60, np.ceil(maxy / 60) * 60
R, B = np.ceil(maxx / 60) * 60, np.floor(miny / 60) * 60
W, H = int((R - L) / 20), int((T - B) / 20)
tr = from_origin(L, T, 20, 20)
inside = ~geometry_mask([mapping(dom)], (H, W), tr)
n_in = int(inside.sum())
print("domain pixels", n_in, file=sys.stderr)

cat = Client.open("https://earth-search.aws.element84.com/v1")
search = cat.search(collections=["sentinel-2-c1-l2a"], bbox=list(dom_ll.bounds),
                    datetime=f"{start}/{end}", max_items=None)
items = list(search.items())
print("items", len(items), file=sys.stderr)
groups = defaultdict(list)
for it in items:
    fp = stransform(to_utm, shape(it.geometry))
    if not fp.intersects(dom):
        continue
    groups[it.properties["s2:datatake_id"]].append(it)

rows = []
env = rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif")
with env:
    for dt, its in sorted(groups.items(), key=lambda kv: kv[1][0].datetime):
        # keep newest baseline per tile
        best = {}
        for it in its:
            tile = it.properties["grid:code"]
            bl = float(it.properties["s2:processing_baseline"])
            best.setdefault(tile, []).append((bl, it))
        keep = []
        for tile, lst in best.items():
            top = max(b for b, _ in lst)
            keep += [it for b, it in lst if b == top]
        scl = np.zeros((H, W), "uint8")
        for it in keep:
            with rasterio.open(it.assets["scl"].href) as src:
                win = from_bounds(L, B, R, T, src.transform)
                a = src.read(1, window=win, boundless=True, fill_value=0, out_shape=(H, W))
            scl = np.where(scl == 0, a, scl)
        v = scl[inside]
        cov = float(np.count_nonzero(v) / n_in)
        valid = float(np.count_nonzero(~np.isin(v, [0, 1, 3, 8, 9, 10])) / n_in)
        fp_cov = unary_union([stransform(to_utm, shape(i.geometry)) for i in keep]).intersection(dom).area / dom.area
        uri = keep[0].properties["s2:product_uri"]
        rows.append(dict(date=keep[0].datetime.date().isoformat(), datatake=dt,
                         orbit=uri.split("_")[4], tiles=sorted({i.properties["grid:code"].replace("MGRS-", "") for i in keep}),
                         n_granules=len(keep), ids=sorted(i.id for i in keep),
                         baselines=sorted({i.properties["s2:processing_baseline"] for i in keep}),
                         eo_cloud_cover=[round(i.properties["eo:cloud_cover"], 1) for i in keep],
                         coverage=round(cov, 4), footprint_cov=round(fp_cov, 4), valid=round(valid, 4),
                         listed=valid >= 0.30))
        print(rows[-1]["date"], rows[-1]["orbit"], rows[-1]["tiles"], rows[-1]["coverage"], rows[-1]["valid"], file=sys.stderr)
Path(out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
