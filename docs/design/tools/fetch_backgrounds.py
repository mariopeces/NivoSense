"""Fetch the two real backgrounds the ramps are tested on.

1. Sentinel-2 L1C true colour (ESA TCI band, 10 m) of S2C_30SVG_20260221_1_L1C from the
   public `sentinel-s2-l1c` bucket (unsigned access), window over the Veleta-Mulhacen crest.
   This is ESA's TCI stretch, not the snow-aware stretch T1.3 will produce.
2. IGN Base gris (ign.es WMTS, CC BY 4.0 scne.es) for the same extent.

Usage: python -I docs/design/tools/fetch_backgrounds.py <out_dir>
"""

from __future__ import annotations

import io
import math
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import transform
from rasterio.windows import from_bounds

# EPSG:32630 window, metres.
BOUNDS = (452000, 4093000, 484000, 4113000)
SIZE = (1600, 1000)
TCI = "s3://sentinel-s2-l1c/tiles/30/S/VG/2026/2/21/1/TCI.jp2"
IGN = (
    "https://www.ign.es/wmts/ign-base?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=IGNBase-gris"
    "&STYLE=default&TILEMATRIXSET=GoogleMapsCompatible&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg"
)


def fetch_l1c(out: Path) -> None:
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    os.environ.setdefault("AWS_REGION", "eu-central-1")
    with rasterio.open(TCI) as ds:
        a = ds.read(window=from_bounds(*BOUNDS, ds.transform), out_shape=(3, SIZE[1], SIZE[0]))
    Image.fromarray(np.moveaxis(a, 0, -1)).save(out)


def merc(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2**z
    return (lon + 180) / 360 * n * 256, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n * 256


def fetch_ign(out: Path, z: int = 13) -> None:
    xs, ys = transform("EPSG:32630", "EPSG:4326", [BOUNDS[0], BOUNDS[2]], [BOUNDS[1], BOUNDS[3]])
    (px0, py1), (px1, py0) = merc(xs[0], ys[0], z), merc(xs[1], ys[1], z)
    tx0, tx1, ty0, ty1 = int(px0 // 256), int(px1 // 256), int(py0 // 256), int(py1 // 256)
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            with urllib.request.urlopen(IGN.format(z=z, x=tx, y=ty), timeout=30) as r:
                mosaic.paste(Image.open(io.BytesIO(r.read())).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
    box = (px0 - tx0 * 256, py0 - ty0 * 256, px1 - tx0 * 256, py1 - ty0 * 256)
    mosaic.crop(tuple(int(v) for v in box)).resize(SIZE, Image.LANCZOS).save(out)


if __name__ == "__main__":
    d = Path(sys.argv[1])
    d.mkdir(parents=True, exist_ok=True)
    fetch_l1c(d / "l1c_tci_20260221.png")
    fetch_ign(d / "ign_base_gris.png")
    print("ok", d)
