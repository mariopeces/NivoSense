import json
from pathlib import Path

import numpy as np

from ..ramps import colour_values, ramps
from .grid import Grid

# README section 6: SWE under 5 mm is drawn transparent, and depth only where SWE reaches it. The ramp holds
# the threshold so the image and the legend share it.
MIN_VISIBLE_SWE_MM = float(ramps()["swe"]["transparent_below"])
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


def write_field_png(path: Path, values: np.ndarray, ramp_id: str) -> None:
    """RGBA image of a model field in the stepped classes of its ramp in docs/design/ramps.json."""
    from PIL import Image

    rgba = colour_values(values, ramp_id)
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


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
