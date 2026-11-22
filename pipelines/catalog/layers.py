"""The published layers and the grid every product of a resolution shares."""

from __future__ import annotations

import math
from dataclasses import dataclass

CRS = "EPSG:32630"

# PMTiles zoom range per resolution. With 512 px tiles, zoom 14 is about 3.8 m per pixel at 37 deg N, so it
# shows every 10 m and 20 m pixel; zoom 12 (about 15 m) does the same for 100 m.
ZOOMS = {10: (8, 14), 20: (8, 14), 100: (8, 12)}


@dataclass(frozen=True)
class Layer:
    id: str
    status: str
    resolution_m: int
    # Class codes, masks and day counts must never be averaged into values that do not exist, so their
    # overviews and tiles use nearest neighbour.
    categorical: bool
    # Tile image format of the PMTiles and, for lossy formats, the encoder quality (10 to 100). Class layers
    # stay lossless PNG; a photographic layer such as true colour uses WebP, about 16 times smaller.
    tile_format: str = "PNG"
    tile_quality: int | None = None
    # Resampling of the display tiles. Layers coloured in stepped ramp classes (docs/design/ramps.json) need
    # nearest neighbour: bilinear blends neighbouring class colours into colours the legend does not have
    # (measured on the 2026-11-20 model SWE: 9 to 23 % of tile pixels per zoom). Only a photograph is smoothed.
    display_resampling: str = "nearest"


LAYERS = {
    layer.id: layer
    for layer in (
        Layer("snow_obs", "observed", 20, categorical=True),
        Layer("snow_gapfill", "gapfilled", 20, categorical=True),
        Layer("swe", "modelled", 100, categorical=False),
        Layer("snow_depth", "modelled", 100, categorical=False),
        # WebP 85 on the full-snow date 2026-01-12, crest Veleta-Mulhacen, zoom 14: 42.8 dB PSNR against PNG
        # (75: 40.9 dB, softens snow texture; 90: 44.1 dB, 30% larger), with no visible blocking.
        Layer("rgb", "observed", 10, categorical=False, tile_format="WEBP", tile_quality=85, display_resampling="bilinear"),
    )
}


def get_layer(layer_id: str) -> Layer:
    try:
        return LAYERS[layer_id]
    except KeyError:
        raise ValueError(f"Unknown layer {layer_id!r}; add it to pipelines/catalog/layers.py") from None


def aligned_bounds(
    left: float, bottom: float, right: float, top: float, resolution_m: int
) -> tuple[float, float, float, float]:
    """Snap EPSG:32630 bounds outwards to the grid of a resolution.

    Pixel edges sit on integer multiples of the resolution from the UTM origin. Sentinel-2 tile corners
    (for example 399960, 4200000 for 30SVF) are multiples of 20 m, so the 10 m and 20 m grids keep the
    native Sentinel-2 pixels, and every 100 m pixel holds exactly 10x10 or 5x5 of them.
    """
    r = resolution_m
    return (
        math.floor(left / r) * r,
        math.floor(bottom / r) * r,
        math.ceil(right / r) * r,
        math.ceil(top / r) * r,
    )


def check_on_grid(crs: str, transform: tuple[float, ...], resolution_m: int) -> None:
    """Raise ValueError unless a raster lies on the shared grid of its layer's resolution."""
    if crs != CRS:
        raise ValueError(f"CRS is {crs}, expected {CRS}")
    a, b, c, d, e, f = transform[:6]
    if b != 0 or d != 0:
        raise ValueError("Rotated rasters are not allowed")
    if a != resolution_m or e != -resolution_m:
        raise ValueError(f"Pixel size is {a} x {-e} m, expected {resolution_m} m square, north up")
    if c % resolution_m != 0 or f % resolution_m != 0:
        raise ValueError(f"Origin ({c}, {f}) is not on the {resolution_m} m grid")
