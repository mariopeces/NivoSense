from pathlib import Path


def build_accumulated_precipitation(inputs: list[Path], destination: Path) -> None:
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling

    total = None
    profile = None
    reference = None
    for path in inputs:
        with rasterio.open(path) as dataset:
            data = dataset.read(1, masked=True).astype("float32")
            current = (dataset.width, dataset.height, dataset.crs, dataset.transform)
            if reference is None:
                reference = current
                profile = dataset.profile.copy()
                total = np.ma.zeros(data.shape, dtype="float32")
            elif current != reference:
                raise ValueError(f"Grid mismatch in {path}")
            total += data

    if total is None or profile is None:
        raise ValueError("At least one precipitation input is required")

    destination.parent.mkdir(parents=True, exist_ok=True)
    profile.update(
        driver="GTiff",
        count=1,
        dtype="float32",
        nodata=-9999.0,
        compress="deflate",
        predictor=3,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    )
    with rasterio.open(destination, "w", **profile) as output:
        output.write(total.filled(-9999.0), 1)
        output.set_band_description(1, "precipitation_total_accumulated_mm")
        output.update_tags(1, units="mm")
        factors = [factor for factor in (2, 4, 8, 16) if min(output.width, output.height) // factor >= 1]
        if factors:
            output.build_overviews(factors, Resampling.average)
            output.update_tags(ns="rio_overview", resampling="average")


def raster_bounds_and_maximum(path: Path) -> tuple[list[float], float]:
    import rasterio

    with rasterio.open(path) as dataset:
        data = dataset.read(1, masked=True)
        maximum = float(data.max()) if data.count() else 0.0
        bounds = [dataset.bounds.left, dataset.bounds.bottom, dataset.bounds.right, dataset.bounds.top]
    return bounds, maximum


def build_precipitation_image(source: Path, destination: Path, scale_max_mm: float) -> None:
    import numpy as np
    import rasterio
    from PIL import Image

    with rasterio.open(source) as dataset:
        data = dataset.read(1, masked=True).astype("float32")
    denominator = scale_max_mm if scale_max_mm > 0 else 1.0
    normalized = np.clip(data.filled(0) / denominator, 0, 1)
    stops = np.array([0.0, 0.2, 0.45, 0.7, 1.0], dtype="float32")
    red = np.interp(normalized, stops, [8, 14, 6, 34, 236])
    green = np.interp(normalized, stops, [47, 116, 182, 211, 254])
    blue = np.interp(normalized, stops, [73, 144, 212, 238, 255])
    alpha = np.where((~data.mask) & (data.filled(0) > 0), 220, 0)
    rgba = np.stack([red, green, blue, alpha], axis=-1).astype("uint8")
    image = Image.fromarray(rgba, mode="RGBA")
    image = image.resize((image.width * 64, image.height * 64), Image.Resampling.NEAREST)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, optimize=True)
