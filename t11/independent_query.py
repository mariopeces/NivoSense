"""Independent check of the S2 ingest: a separate code path (pystac-client, bbox search,
grouping by datatake, shapely footprints, rasterio.merge for SCL) that shares no code with
pipelines/s2.

usage: python independent_query.py DOMAIN.geojson START END OUT.json [--pixels]
"""
import json
import sys
from collections import defaultdict

import numpy as np
import rasterio
from pystac_client import Client
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.warp import transform_geom
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

domain_path, start, end, out_path = sys.argv[1:5]
pixels = "--pixels" in sys.argv

features = json.load(open(domain_path, encoding="utf-8"))["features"]
domain_ll = unary_union([shape(f["geometry"]) for f in features])
domain_utm = shape(transform_geom("EPSG:4326", "EPSG:32630", mapping(domain_ll)))

client = Client.open("https://earth-search.aws.element84.com/v1")
search = client.search(
    collections=["sentinel-2-c1-l2a"], bbox=list(domain_ll.bounds), datetime=f"{start}/{end}", max_items=None
)
groups = defaultdict(list)
for item in search.items():
    footprint = shape(item.geometry)
    if not footprint.intersects(domain_ll):
        continue
    groups[(item.datetime.date().isoformat(), item.properties["s2:datatake_id"])].append(item)

rows = []
for (day, datatake), items in sorted(groups.items()):
    footprints_utm = unary_union(
        [shape(transform_geom("EPSG:4326", "EPSG:32630", item.geometry)) for item in items]
    )
    row = {
        "date": day,
        "datatake": datatake,
        "orbit": "R" + items[0].properties["s2:product_uri"].split("_R")[1][:3],
        "tiles": sorted(item.properties["grid:code"].replace("MGRS-", "") for item in items),
        "footprint_coverage": round(footprints_utm.intersection(domain_utm).area / domain_utm.area, 4),
    }
    if pixels:
        left, bottom, right, top = domain_utm.bounds
        left, bottom = np.floor(left / 20) * 20, np.floor(bottom / 20) * 20
        right, top = np.ceil(right / 20) * 20, np.ceil(top / 20) * 20
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            sources = [rasterio.open(item.assets["scl"].href) for item in items]
            scl, transform = merge(sources, bounds=(left, bottom, right, top), res=20, nodata=0)
            for source in sources:
                source.close()
        scl = scl[0]
        inside = ~geometry_mask([mapping(domain_utm)], out_shape=scl.shape, transform=transform)
        values = scl[inside]
        row["pixel_coverage"] = round(float(np.mean(values != 0)), 4)
        row["pixel_valid_fraction"] = round(float(np.mean(~np.isin(values, [0, 1, 3, 8, 9, 10]))), 4)
    rows.append(row)
    print(row, flush=True)

json.dump(rows, open(out_path, "w"), indent=1)
