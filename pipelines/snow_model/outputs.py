import json
from pathlib import Path

import numpy as np

from .grid import Grid

PALETTES = {
    "swe": ((20, 33, 99), (47, 97, 214), (96, 165, 250), (186, 230, 253), (255, 255, 255)),
    "depth": ((60, 40, 120), (99, 102, 241), (129, 180, 250), (207, 233, 254), (255, 255, 255)),
}
STOPS = np.array([0.0, 0.2, 0.45, 0.7, 1.0])
MIN_VISIBLE_SWE_MM = 5.0
MIN_VISIBLE_DEPTH_M = 0.03
SNOW_RGB = (103, 232, 249)


def to_grid(values: np.ndarray, cell_index: np.ndarray, grid: Grid) -> np.ndarray:
    full = np.full(grid.height * grid.width, np.nan, dtype="float32")
    full[cell_index] = values
    return full.reshape(grid.height, grid.width)


def write_geotiff(path: Path, bands: list[tuple[np.ndarray, str]], grid: Grid) -> None:
    import rasterio

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=grid.width,
        height=grid.height,
        count=len(bands),
        dtype="float32",
        crs=grid.crs,
        transform=grid.transform,
        nodata=-9999.0,
        compress="deflate",
        predictor=3,
    ) as output:
        for index, (array, description) in enumerate(bands, start=1):
            output.write(np.nan_to_num(array, nan=-9999.0).astype("float32"), index)
            output.set_band_description(index, description)


def write_field_png(
    path: Path, values: np.ndarray, scale_max: float, palette: str, minimum: float
) -> None:
    from PIL import Image

    normalized = np.clip(np.nan_to_num(values) / max(scale_max, 1e-6), 0, 1)
    channels = [
        np.interp(normalized, STOPS, [color[channel] for color in PALETTES[palette]])
        for channel in range(3)
    ]
    alpha = np.where(np.nan_to_num(values) >= minimum, 235, 0)
    rgba = np.stack(channels + [alpha], axis=-1).astype("uint8")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path, optimize=True)


def write_observation_png(path: Path, snow: np.ndarray, valid: np.ndarray) -> None:
    """Palette image at 10 m: transparent where clear and snow-free, cyan snow, grey gaps."""
    from PIL import Image

    classes = np.where(valid, np.where(snow, 1, 0), 2).astype("uint8")
    image = Image.fromarray(classes, mode="P")
    image.putpalette([0, 0, 0, *SNOW_RGB, 120, 130, 145] + [0] * (256 - 3) * 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True, transparency=bytes([0, 235, 110]))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
