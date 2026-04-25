"""
Reproject and resample any raster to a common reference grid.

The reference grid is taken from a Sentinel-2 band (natively 10 m, UTM Zone 30N).
The CNIG MDT05 is at 5 m and must be resampled to 10 m before stacking with S2.
"""
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject


def get_reference_grid(s2_path: str) -> dict:
    """
    Extract CRS, transform, and shape from an S2 GeoTIFF (already at 10 m).
    Use a B03 or B04 file as reference.
    """
    with rasterio.open(s2_path) as src:
        return {
            "crs": src.crs,
            "transform": src.transform,
            "width": src.width,
            "height": src.height,
        }


def align_to_grid(
    src_array: np.ndarray,
    src_profile: dict,
    ref_grid: dict,
    resampling: Resampling = Resampling.bilinear,
) -> tuple[np.ndarray, dict]:
    """
    Reproject src_array to match ref_grid's CRS, transform and shape.

    Parameters
    ----------
    src_array   : 2-D numpy array
    src_profile : rasterio profile of src_array (must contain crs, transform)
    ref_grid    : dict from get_reference_grid()
    resampling  : use Resampling.bilinear for continuous data,
                  Resampling.nearest for categorical (elevation_bands, SCL)

    Returns
    -------
    dst_array   : reprojected array with same dtype as src_array
    dst_profile : updated rasterio profile
    """
    nodata = src_profile.get("nodata", np.nan)
    dst_array = np.full(
        (ref_grid["height"], ref_grid["width"]),
        nodata,
        dtype=src_array.dtype,
    )

    reproject(
        source=src_array,
        destination=dst_array,
        src_transform=src_profile["transform"],
        src_crs=src_profile["crs"],
        dst_transform=ref_grid["transform"],
        dst_crs=ref_grid["crs"],
        resampling=resampling,
    )

    dst_profile = src_profile.copy()
    dst_profile.update(
        crs=ref_grid["crs"],
        transform=ref_grid["transform"],
        width=ref_grid["width"],
        height=ref_grid["height"],
    )
    return dst_array, dst_profile
