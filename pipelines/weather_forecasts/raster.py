from pathlib import Path

from .config import MIN_VISIBLE_MM

PALETTES = {
    "precipitation_total": (
        (8, 47, 73),
        (14, 116, 144),
        (6, 182, 212),
        (34, 211, 238),
        (236, 254, 255),
    ),
    "snowfall": (
        (45, 35, 110),
        (79, 70, 229),
        (129, 140, 248),
        (199, 210, 254),
        (255, 255, 255),
    ),
}


def _write_field(destination: Path, data, transform, crs, description: str) -> None:
    import rasterio
    from rasterio.enums import Resampling

    destination.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        destination,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
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
        output.update_tags(1, units="mm")
        factors = [factor for factor in (2, 4, 8, 16) if min(output.width, output.height) // factor >= 1]
        if factors:
            output.build_overviews(factors, Resampling.average)
            output.update_tags(ns="rio_overview", resampling="average")


def build_accumulated_precipitation(inputs: list[Path], destination: Path) -> None:
    import numpy as np
    import rasterio

    total = None
    reference = None
    transform = None
    crs = None
    for path in inputs:
        with rasterio.open(path) as dataset:
            data = dataset.read(1, masked=True).astype("float32")
            current = (dataset.width, dataset.height, dataset.crs, dataset.transform)
            if reference is None:
                reference = current
                transform = dataset.transform
                crs = dataset.crs
                total = np.ma.zeros(data.shape, dtype="float32")
            elif current != reference:
                raise ValueError(f"Grid mismatch in {path}")
            total += data

    if total is None:
        raise ValueError("At least one precipitation input is required")

    _write_field(destination, total, transform, crs, "precipitation_total_accumulated_mm")


def build_regional_field(
    source: Path,
    bbox: tuple[float, float, float, float],
    destination: Path,
    multiplier: float,
    description: str,
) -> None:
    import math

    import eccodes
    import numpy as np
    from rasterio.transform import from_origin

    with source.open("rb") as handle:
        message = eccodes.codes_grib_new_from_file(handle)
    try:
        get = lambda key: eccodes.codes_get(message, key)
        if get("jScansPositively") or get("iScansNegatively"):
            raise ValueError("Unsupported GRIB scanning mode")
        columns, rows = get("Ni"), get("Nj")
        step_x = get("iDirectionIncrementInDegrees")
        step_y = get("jDirectionIncrementInDegrees")
        first_lon = (get("longitudeOfFirstGridPointInDegrees") + 180) % 360 - 180
        first_lat = get("latitudeOfFirstGridPointInDegrees")
        values = eccodes.codes_get_values(message).reshape(rows, columns)
    finally:
        eccodes.codes_release(message)

    west, south, east, north = bbox
    col0 = math.floor((west - first_lon) / step_x + 0.5)
    col1 = math.floor((east - first_lon) / step_x + 0.5)
    row0 = math.floor((first_lat - north) / step_y + 0.5)
    row1 = math.floor((first_lat - south) / step_y + 0.5)
    if col0 < 0 or row0 < 0 or col1 >= columns or row1 >= rows:
        raise ValueError("Region is outside the GRIB grid")

    data = np.ma.masked_invalid(values[row0 : row1 + 1, col0 : col1 + 1].astype("float32")) * multiplier
    transform = from_origin(
        first_lon + col0 * step_x - step_x / 2,
        first_lat - row0 * step_y + step_y / 2,
        step_x,
        step_y,
    )
    # The GRIB grid is a spherical lat/lon grid; at this scale it is plotted as EPSG:4326.
    _write_field(destination, data, transform, "EPSG:4326", description)


def raster_bounds_and_maximum(path: Path) -> tuple[list[float], float]:
    import rasterio

    with rasterio.open(path) as dataset:
        data = dataset.read(1, masked=True)
        maximum = float(data.max()) if data.count() else 0.0
        bounds = [dataset.bounds.left, dataset.bounds.bottom, dataset.bounds.right, dataset.bounds.top]
    return bounds, maximum


def build_field_image(source: Path, destination: Path, scale_max_mm: float, variable: str) -> None:
    import numpy as np
    import rasterio
    from PIL import Image

    with rasterio.open(source) as dataset:
        data = dataset.read(1, masked=True).astype("float32")
    denominator = scale_max_mm if scale_max_mm > 0 else 1.0
    normalized = np.clip(data.filled(0) / denominator, 0, 1)
    stops = np.array([0.0, 0.2, 0.45, 0.7, 1.0], dtype="float32")
    red, green, blue = (
        np.interp(normalized, stops, [color[channel] for color in PALETTES[variable]])
        for channel in range(3)
    )
    alpha = np.where((~data.mask) & (data.filled(0) >= MIN_VISIBLE_MM), 220, 0)
    rgba = np.stack([red, green, blue, alpha], axis=-1).astype("uint8")
    image = Image.fromarray(rgba, mode="RGBA")
    image = image.resize((image.width * 64, image.height * 64), Image.Resampling.NEAREST)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, optimize=True)
