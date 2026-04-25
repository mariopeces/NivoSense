"""
End-to-end data preparation for one Sentinel-2 acquisition.

Reads directly from GCS (rasterio uses GDAL /vsigs/ — requires
gcloud application-default credentials or GOOGLE_APPLICATION_CREDENTIALS).

Output: multi-band GeoTIFF at 10 m resolution with 5 bands:
  1  ndsi               float32   cloud-masked NDSI [−1, 1]
  2  elevation_m        float32   metres
  3  slope_deg          float32   degrees [0, 90]
  4  aspect_deg         float32   degrees from North [0, 360)
  5  elevation_band     float32   discrete band index (200 m intervals)

Usage
-----
    from ml.data_preparation import prepare_acquisition

    out = prepare_acquisition(
        year=2021,
        month="jan",
        timestamp="20210115t104321z",
        dem_path="gs://your-bucket/mdt05_sierra_nevada.tif",
        output_dir="/tmp/features",
    )
"""
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.env import Env

from .ndsi import compute_ndsi
from .dem import load_dem_layers
from .align import get_reference_grid, align_to_grid

# GDAL network timeouts — prevents hanging on slow/dropped GCS connections
_GDAL_ENV = {
    "GDAL_HTTP_TIMEOUT": "60",
    "CPL_VSIL_CURL_TIMEOUT": "60",
    "GDAL_HTTP_RETRY_COUNT": "3",
    "GDAL_HTTP_RETRY_DELAY": "5",
    "CPL_VSIL_CURL_NON_CACHED": "/vsigs/",
}

_GCS_BASE = (
    "gs://darwin-general-hdh-sandbox-tiles"
    "/tiles/guest/raster/temporal/s2_raw_images"
)


def _band_path(year: int, month: str, band: str, timestamp: str) -> str:
    fname = f"s2_raw_images_{band}_{year}_{month}_sierra_nevada_{timestamp}.tif"
    return f"{_GCS_BASE}/{year}/{month}/{fname}"


def prepare_acquisition(
    year: int,
    month: str,
    timestamp: str,
    dem_path: str,
    output_dir: str,
    elevation_band_interval_m: float = 200.0,
) -> Path:
    """
    Process one S2 acquisition into a 5-band feature GeoTIFF.

    Parameters
    ----------
    year, month, timestamp : identify the acquisition
        e.g. year=2021, month="jan", timestamp="20210115t104321z"
    dem_path : path or gs:// URI to the CNIG MDT05 GeoTIFF
    output_dir : local directory for the output file
    elevation_band_interval_m : width of each elevation band in metres

    Returns
    -------
    Path to the written output file.
    """
    b03_path = _band_path(year, month, "b03", timestamp)
    b11_path = _band_path(year, month, "b11", timestamp)
    scl_path = _band_path(year, month, "scl", timestamp)

    with Env(**_GDAL_ENV):
        # 1. NDSI + cloud mask (already at 10 m, B11/SCL upsampled internally)
        ndsi, ndsi_profile = compute_ndsi(b03_path, b11_path, scl_path)

        # 2. Reference grid from B03 (10 m, UTM)
        ref_grid = get_reference_grid(b03_path)

    # 3. DEM layers at native 5 m → align to 10 m reference grid
    dem_layers = load_dem_layers(dem_path, interval_m=elevation_band_interval_m)
    aligned = {}
    for name, (arr, prof) in dem_layers.items():
        resamp = Resampling.nearest if name == "elevation_bands" else Resampling.bilinear
        aligned[name], _ = align_to_grid(arr, prof, ref_grid, resampling=resamp)

    # 4. Write 5-band output
    out_profile = ndsi_profile.copy()
    out_profile.update(count=5, dtype="float32", compress="deflate", nodata=np.nan)

    out_path = Path(output_dir) / f"ndsi_{year}_{month}_{timestamp}.tif"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(out_path, "w", **out_profile) as dst:
        dst.write(ndsi, 1)
        dst.write(aligned["elevation"], 2)
        dst.write(aligned["slope"], 3)
        dst.write(aligned["aspect"], 4)
        dst.write(aligned["elevation_bands"].astype(np.float32), 5)
        dst.update_tags(
            band_1="ndsi",
            band_2="elevation_m",
            band_3="slope_deg",
            band_4="aspect_deg_from_north",
            band_5="elevation_band_index",
        )

    return out_path
