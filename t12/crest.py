"""Crest check (README Q4 box) and thumbnails: class counts inside the box, outside the ski resort.

python crest.py <s2 dir> <snow_obs dir> <date> <ski_resort.geojson> <out dir>
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.features import rasterize
from rasterio.warp import transform_bounds, transform_geom
from rasterio.windows import from_bounds

s2, obs, day, resort_path, out = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), Path(sys.argv[5])
out.mkdir(parents=True, exist_ok=True)
BBOX = (-3.42, 37.01, -3.30, 37.07)
summary = json.loads((obs / day / "summary.json").read_text())
with rasterio.open(obs / day / "snow_obs.tif") as src:
    bounds = transform_bounds("EPSG:4326", src.crs, *BBOX, densify_pts=21)
    window = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
    classes, confidence, flags = src.read(window=window)
    transform = src.window_transform(window)
with rasterio.open(s2 / day / summary["orbit"] / "reflectance.tif") as src:
    refl = {name: src.read(i, window=window) for i, name in enumerate(src.descriptions, start=1)}
resort = json.loads(resort_path.read_text())
shapes = [transform_geom("EPSG:4326", "EPSG:32630", f["geometry"]) for f in resort["features"]]
in_resort = rasterize(shapes, out_shape=classes.shape, transform=transform, all_touched=True).astype(bool)
names = {0: "no_snow", 1: "snow", 2: "cloud", 3: "unknown", 255: "outside_domain"}
def counts(mask):
    return {names[int(v)]: int(n) for v, n in zip(*np.unique(classes[mask], return_counts=True))}
report = {
    "date": day,
    "bbox_lonlat": BBOX,
    "pixels_in_box": int(classes.size),
    "outside_resort": counts(~in_resort),
    "inside_resort": counts(in_resort),
    "snow_outside_resort_flags": {
        "terrain_shadow": int(((classes == 1) & ~in_resort & (flags & 2 > 0)).sum()),
        "pass2": int(((classes == 1) & ~in_resort & (flags & 4 > 0)).sum()),
        "bright_snow_fix": int(((classes == 1) & ~in_resort & (flags & 8 > 0)).sum()),
    },
}
(out / f"crest_{day}.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))

# SWIR false colour (B11, B8A not ingested -> B11, B03... use B11/B04/B03), stretched 0..0.6
def stretch(a, hi=0.6):
    return (np.clip(np.nan_to_num(a) / hi, 0, 1) ** (1 / 1.5) * 255).astype("uint8")
false = np.dstack([stretch(refl["swir16"]), stretch(refl["red"]), stretch(refl["green"])])
overlay = false.copy()
palette = {1: (62, 72, 145), 2: (244, 242, 238), 3: (46, 51, 59)}
for code, colour in palette.items():
    overlay[classes == code] = colour
edge = in_resort ^ np.roll(in_resort, 1, 0) | in_resort ^ np.roll(in_resort, 1, 1)
overlay[edge] = (230, 80, 40)
scale = 2
for name, img in (("swir_false_colour", false), ("classes", overlay)):
    Image.fromarray(img).resize((img.shape[1] * scale, img.shape[0] * scale), Image.NEAREST).save(out / f"crest_{day}_{name}.png")
