"""Quick-look PNGs of an ingested acquisition: red/green/swir16 composite and SCL classes,
with the domain outline, downsampled 2x. usage: render.py RUN_DIR DATE ORBIT DOMAIN OUT.png"""
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

sys.path.insert(0, ".")  # run from the repository root
from pipelines.s2.domain import load_domain  # noqa: E402

run, day, orbit, domain_path, out = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
folder = run / day / orbit
with rasterio.open(folder / "reflectance.tif") as src:
    green, red, swir = src.read(1), src.read(2), src.read(3)
with rasterio.open(folder / "classes.tif") as src:
    scl = src.read(1)
mask = load_domain(domain_path).mask
edge = mask ^ (np.roll(mask, 1, 0) & np.roll(mask, -1, 0) & np.roll(mask, 1, 1) & np.roll(mask, -1, 1))


def stretch(a):
    return np.clip(np.nan_to_num(a, nan=0) / 0.6 * 255, 0, 255).astype("uint8")


rgb = np.dstack([stretch(red), stretch(green), stretch(swir)])
palette = {0: (0, 0, 0), 1: (255, 0, 0), 2: (60, 60, 60), 3: (100, 60, 20), 4: (0, 160, 0), 5: (200, 170, 100),
           6: (0, 0, 255), 7: (128, 128, 128), 8: (190, 190, 190), 9: (240, 240, 240), 10: (150, 200, 255),
           11: (255, 0, 255)}
classes = np.zeros(scl.shape + (3,), dtype="uint8")
for value, colour in palette.items():
    classes[scl == value] = colour
for image in (rgb, classes):
    image[edge] = (255, 255, 0)
both = np.concatenate([rgb, classes], axis=0)[::2, ::2]
Image.fromarray(both).save(out)
print(out, both.shape)
