"""Side-by-side thumbnails: SWIR false colour (B11/B4/B3) and the snow_obs classes drawn with the
product's own display colours over it. python thumbs.py <s2 dir> <snow_obs dir> <out dir> <date>..."""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

s2, obs, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
step = 4
for day in sys.argv[4:]:
    summary = json.loads((obs / day / "summary.json").read_text())
    with rasterio.open(s2 / day / summary["orbit"] / "reflectance.tif") as src:
        g, r, w = src.read()[:, ::step, ::step]
    with rasterio.open(obs / day / "display.tif") as src:
        rgba = src.read()[:, ::step, ::step].astype("float32") / 255
    with rasterio.open(obs / day / "snow_obs.tif") as src:
        cls = src.read(1)[::step, ::step]
    st = lambda a: (np.clip(np.nan_to_num(a) / 0.8, 0, 1) ** (1 / 1.6) * 255)
    fc = np.dstack([st(w), st(r), st(g)])
    alpha = rgba[3][..., None]
    over = fc * (1 - alpha) + np.moveaxis(rgba[:3], 0, -1) * 255 * alpha
    over[cls == 255] *= 0.35
    img = np.vstack([fc, over]).astype("uint8")
    Image.fromarray(img).save(out / f"thumb_{day}.png")
    print(day, summary["observed_fraction"], summary["counts"], summary["snowline_m"])
