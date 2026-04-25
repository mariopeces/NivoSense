"""
NDSI computation and cloud masking from Sentinel-2 L2A bands.

NDSI = (B03 - B11) / (B03 + B11)

SCL classes masked out (clouds, shadows, defective):
  0  No Data
  1  Saturated / Defective
  2  Dark Area (cast shadows)
  3  Cloud Shadows
  8  Cloud Medium Probability
  9  Cloud High Probability
  10 Thin Cirrus
"""
import numpy as np
import rasterio
from rasterio.enums import Resampling

_CLOUD_SCL = frozenset({0, 1, 2, 3, 8, 9, 10})


def compute_ndsi(
    b03_path: str,
    b11_path: str,
    scl_path: str,
) -> tuple[np.ndarray, dict]:
    """
    Compute cloud-masked NDSI for one S2 acquisition.

    B11 and SCL are at 20m native resolution; they are upsampled to match
    the B03 grid (10m) before computing NDSI. Masked pixels are set to NaN.

    Returns
    -------
    ndsi : float32 array shaped (height, width)
    profile : rasterio profile for writing the result
    """
    with rasterio.open(b03_path) as src:
        profile = src.profile.copy()
        height, width = src.height, src.width
        b03 = src.read(1).astype(np.float32)

    # Read B11 and SCL resampled to B03 shape (handles 20m → 10m if needed)
    with rasterio.open(b11_path) as src:
        b11 = src.read(
            1,
            out_shape=(height, width),
            resampling=Resampling.bilinear,
        ).astype(np.float32)

    with rasterio.open(scl_path) as src:
        scl = src.read(
            1,
            out_shape=(height, width),
            resampling=Resampling.nearest,
        )

    # S2 L2A BOA reflectance is in [0, 10000]; negative values are
    # atmospheric correction artifacts — treat them as invalid
    b03 = np.where(b03 > 0, b03, np.nan)
    b11 = np.where(b11 > 0, b11, np.nan)

    denominator = b03 + b11
    with np.errstate(divide="ignore", invalid="ignore"):
        ndsi = np.where(denominator != 0, (b03 - b11) / denominator, np.nan)

    # Clip to valid NDSI range as a final sanity check
    ndsi = np.clip(ndsi, -1.0, 1.0)

    # Mask clouds/shadows
    ndsi[np.isin(scl, list(_CLOUD_SCL))] = np.nan

    profile.update(dtype="float32", count=1, nodata=np.nan)
    return ndsi, profile
