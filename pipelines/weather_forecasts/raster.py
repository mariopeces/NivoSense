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
