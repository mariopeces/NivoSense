"""Two platforms on one relative orbit and day: run PR #14's ingest (imported from the PR
checkout) and check the stored mosaic against an independent per-datatake SCL mosaic.
Usage: python two_platforms.py <pr checkout> <domain geojson> <out dir> YYYY-MM-DD [...]"""
import json, sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.merge import merge
from rasterio.warp import transform_geom
from pystac_client import Client

pr, domain_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(pr))
from pipelines.s2 import ingest  # noqa: E402  (PR code; used only to produce the records)

NOT_VALID = (0, 1, 3, 8, 9, 10)
gj = json.loads(domain_path.read_text(encoding="utf-8"))
geoms = [f["geometry"] for f in gj["features"]]
client = Client.open("https://earth-search.aws.element84.com/v1")

for day_s in sys.argv[4:]:
    day = date.fromisoformat(day_s)
    records = ingest.run(domain_path, day, day, out, today=day, version="g-code-r2")
    lons = [c[0] for g in geoms for ring in (g["coordinates"] if g["type"] == "Polygon" else [r for p in g["coordinates"] for r in p]) for c in ring]
    lats = [c[1] for g in geoms for ring in (g["coordinates"] if g["type"] == "Polygon" else [r for p in g["coordinates"] for r in p]) for c in ring]
    items = list(client.search(collections=["sentinel-2-c1-l2a"], bbox=[min(lons), min(lats), max(lons), max(lats)],
                               datetime=f"{day_s}T00:00:00Z/{day_s}T23:59:59Z").items())
    by_pass = defaultdict(lambda: defaultdict(list))
    for it in items:
        orbit = it.properties["s2:product_uri"].split("_")[4]
        by_pass[orbit][it.properties["s2:datatake_id"].rsplit("_N", 1)[0]].append(it)
    for record in records:
        if record["date"] != day_s:
            continue
        folder = out / day_s / record["orbit"]
        with rasterio.open(folder / "classes.tif") as src:
            stored, tr, shape, crs = src.read(1), src.transform, (src.height, src.width), src.crs
        mask = rasterize([(transform_geom("EPSG:4326", crs, g), 1) for g in geoms], out_shape=shape, transform=tr, dtype="uint8").astype(bool)
        bounds = rasterio.transform.array_bounds(shape[0], shape[1], tr)
        own = {}
        for dt, its in sorted(by_pass[record["orbit"]].items()):
            newest = max(float(i.properties["s2:processing_baseline"]) for i in its)
            srcs = [rasterio.open(i.assets["scl"].href) for i in sorted(its, key=lambda i: i.id)
                    if float(i.properties["s2:processing_baseline"]) == newest]
            arr, _ = merge(srcs, bounds=(bounds[0], bounds[1], bounds[2], bounds[3]), res=20, nodata=0)
            for s in srcs:
                s.close()
            scl = arr[0][: shape[0], : shape[1]]
            m = scl[mask]
            own[dt] = scl
            cov = np.count_nonzero(m) / m.size
            val = np.count_nonzero(~np.isin(m, NOT_VALID)) / m.size
            same = np.count_nonzero(stored[mask] == m) / m.size
            print(f"{day_s} {record['orbit']} {dt}: indep coverage {cov:.4f} valid {val:.4f}; stored==this datatake on {same:.4%} of domain px")
        chosen = record["datatake"]
        others = [d for d in own if d != chosen]
        if others:
            o = own[others[0]]
            c = own[chosen]
            differ = mask & (c != o)
            from_other = np.count_nonzero(differ & (stored == o))
            from_chosen = np.count_nonzero(differ & (stored == c))
            print(f"  record: datatake {chosen} coverage {record['domain_coverage']} valid {record['domain_valid_fraction']} "
                  f"complete {record['complete']} listed {record['listed']} tiles {record['tiles']}")
            print(f"  alternatives: {json.dumps(record['alternatives'])}")
            print(f"  domain px where the two datatakes' SCL differ: {np.count_nonzero(differ)}; stored takes chosen on {from_chosen}, other on {from_other}")
        else:
            print(f"  record: datatake {chosen} (single datatake) coverage {record['domain_coverage']} valid {record['domain_valid_fraction']}")
