from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .config import MIN_VISIBLE_MM

if TYPE_CHECKING:
    import numpy as np
    from affine import Affine
    from rasterio.crs import CRS

# The frontend legend reads the same file, so it always shows the colours painted here.
PALETTES_JSON = Path(__file__).with_name("palettes.json")
_PALETTES = json.loads(PALETTES_JSON.read_text(encoding="utf-8"))
PALETTES = {
    variable: tuple(tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5)) for colour in colours)
    for variable, colours in _PALETTES["palettes"].items()
}
STOPS = tuple(float(stop) for stop in _PALETTES["stops"])
ALPHA = int(_PALETTES["alpha"])
# Variables drawn on a fixed display range instead of the run maximum.
FIXED_SCALES = {name: (float(item["min"]), float(item["max"])) for name, item in _PALETTES["scales"].items()}


def _write_field(
    destination: Path,
    data: np.ma.MaskedArray,
    transform: Affine,
    crs: CRS | str,
    description: str,
    extra: tuple[tuple[np.ndarray, str], ...] = (),
    units: str = "mm",
) -> None:
    import rasterio
    from rasterio.enums import Resampling

    destination.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        destination,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1 + len(extra),
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=-9999.0,
        compress="deflate",
        predictor=3,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as output:
        output.write(data.filled(-9999.0), 1)
        output.set_band_description(1, description)
        output.update_tags(1, units=units)
        for index, (band, band_description) in enumerate(extra, start=2):
            output.write(band.astype("float32"), index)
            output.set_band_description(index, band_description)
            output.update_tags(index, units=units)
        factors = [factor for factor in (2, 4, 8, 16) if min(output.width, output.height) // factor >= 1]
        if factors:
            output.build_overviews(factors, Resampling.average)
            output.update_tags(ns="rio_overview", resampling="average")


def build_grid_field(
    values: np.ndarray,
    transform: Affine,
    destination: Path,
    description: str,
    units: str,
) -> None:
    """Writes a north-up EPSG:4326 field; NaN cells become nodata."""
    import numpy as np

    data = np.ma.masked_invalid(values.astype("float32"))
    _write_field(destination, data, transform, "EPSG:4326", description, units=units)


def build_classified_field(decoded: list, transform: Affine, destination: Path) -> None:
    import numpy as np

    estimate = np.ma.masked_array(sum(item[2] for item in decoded))
    lower = sum(item[0] for item in decoded)
    upper = sum(item[1] for item in decoded)
    _write_field(
        destination,
        estimate,
        transform,
        "EPSG:4326",
        "precipitation_total_accumulated_mm_class_estimate",
        extra=(
            (lower, "precipitation_total_accumulated_mm_lower_bound"),
            (upper, "precipitation_total_accumulated_mm_upper_bound"),
        ),
    )


def raster_bounds_and_range(path: Path) -> tuple[list[float], float, float]:
    import rasterio

    with rasterio.open(path) as dataset:
        data = dataset.read(1, masked=True)
        minimum = float(data.min()) if data.count() else 0.0
        maximum = float(data.max()) if data.count() else 0.0
        bounds = [dataset.bounds.left, dataset.bounds.bottom, dataset.bounds.right, dataset.bounds.top]
    return bounds, minimum, maximum


def build_field_image(
    source: Path, destination: Path, scale_min: float, scale_max: float, variable: str
) -> None:
    import numpy as np
    import rasterio
    from PIL import Image

    with rasterio.open(source) as dataset:
        data = dataset.read(1, masked=True).astype("float32")
    denominator = scale_max - scale_min if scale_max > scale_min else 1.0
    normalized = np.clip((data.filled(scale_min) - scale_min) / denominator, 0, 1)
    stops = np.array(STOPS, dtype="float32")
    red, green, blue = (
        np.interp(normalized, stops, [color[channel] for color in PALETTES[variable]])
        for channel in range(3)
    )
    # Accumulations hide near-zero cells; temperature and wind are painted wherever they are defined.
    visible = ~np.ma.getmaskarray(data)
    if variable not in FIXED_SCALES:
        visible &= data.filled(0) >= MIN_VISIBLE_MM
    alpha = np.where(visible, ALPHA, 0)
    rgba = np.stack([red, green, blue, alpha], axis=-1).astype("uint8")
    image = Image.fromarray(rgba, mode="RGBA")
    image = image.resize((image.width * 64, image.height * 64), Image.Resampling.NEAREST)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, optimize=True)
