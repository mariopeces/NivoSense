"""Thumbnails of builder outputs: false colour (swir16, red, green -> R,G,B is SWIR composite; snow cyan,
cloud white) and red/green/green pseudo-true colour, plus SCL. 80 m, domain outline."""
import sys, json, numpy as np, rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from PIL import Image
folder, outpng, domain = sys.argv[1], sys.argv[2], sys.argv[3]
with rasterio.open(folder + "/reflectance.tif") as r:
    g, red, sw = r.read(); tr = r.transform; shp = (r.height, r.width)
with rasterio.open(folder + "/classes.tif") as c:
    scl = c.read(1)
gj = json.load(open(domain, encoding="utf-8"))
geoms = [transform_geom("EPSG:4326", "EPSG:32630", f["geometry"]) for f in gj["features"]]
inside = ~geometry_mask(geoms, shp, tr)
edge = inside ^ np.roll(inside, 1, 0) | inside ^ np.roll(inside, 1, 1)
def st(a, lo=0.0, hi=0.6):
    x = np.clip((np.nan_to_num(a, nan=0) - lo) / (hi - lo), 0, 1)
    return (x ** 0.8 * 255).astype("uint8")
fc = np.dstack([st(sw), st(red), st(g)])
tc = np.dstack([st(red, 0, 0.35), st(g, 0, 0.35), st(g, 0, 0.35)])
pal = {0: (0, 0, 0), 1: (255, 0, 0), 2: (60, 60, 60), 3: (100, 50, 0), 4: (0, 160, 0), 5: (255, 230, 90), 6: (0, 0, 255), 7: (128, 128, 128), 8: (190, 190, 190), 9: (255, 255, 255), 10: (100, 200, 255), 11: (255, 100, 255)}
sc = np.zeros(shp + (3,), "uint8")
for k, v in pal.items(): sc[scl == k] = v
for im in (fc, tc, sc): im[edge] = (255, 255, 0)
step = 4
panel = np.concatenate([im[::step, ::step] for im in (tc, fc, sc)], axis=1)
Image.fromarray(panel).save(outpng)
print(outpng, panel.shape)
