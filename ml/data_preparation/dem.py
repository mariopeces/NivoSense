"""
DEM-derived layers from the CNIG MDT05 (5 m resolution).

Derived layers
--------------
elevation       : raw elevation values (m), float32
slope           : steepest descent angle in degrees [0, 90], float32
aspect          : direction of max slope in degrees from North [0, 360), float32
elevation_bands : discrete elevation bands (interval_m wide), int16
"""
import numpy as np
import rasterio


def _slope_aspect(dem: np.ndarray, cell_size_m: float) -> tuple[np.ndarray, np.ndarray]:
    # numpy gradient returns [dy (row/N-S), dx (col/E-W)]
    dy, dx = np.gradient(dem.astype(np.float64), cell_size_m)

    slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))

    # arctan2 gives CCW angle from east; convert to CW degrees from north
    aspect = np.degrees(np.arctan2(-dy, dx))
    aspect = (aspect + 360.0) % 360.0

    return slope.astype(np.float32), aspect.astype(np.float32)


def _elevation_bands(dem: np.ndarray, interval_m: float) -> np.ndarray:
    min_elev = np.nanmin(dem)
    bands = np.floor((dem - min_elev) / interval_m).astype(np.int16)
    return bands


def load_dem_layers(
    dem_path: str,
    interval_m: float = 200.0,
) -> dict[str, tuple[np.ndarray, dict]]:
    """
    Load the DEM and compute slope, aspect, and elevation bands.

    Parameters
    ----------
    dem_path : path or gs:// URI to the CNIG MDT05 GeoTIFF
    interval_m : elevation band width in metres (default 200 m)

    Returns
    -------
    dict mapping layer name → (array, rasterio_profile):
      "elevation"       float32
      "slope"           float32  (degrees)
      "aspect"          float32  (degrees from North)
      "elevation_bands" int16
    """
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float32)
        base_profile = src.profile.copy()
        cell_size_m = abs(src.transform.a)  # pixel width in CRS units (metres for UTM)

    slope, aspect = _slope_aspect(dem, cell_size_m)
    elev_bands = _elevation_bands(dem, interval_m)

    float_profile = base_profile.copy()
    float_profile.update(dtype="float32", count=1, nodata=np.nan)

    int_profile = base_profile.copy()
    int_profile.update(dtype="int16", count=1, nodata=-9999)

    return {
        "elevation": (dem, float_profile),
        "slope": (slope, float_profile),
        "aspect": (aspect, float_profile),
        "elevation_bands": (elev_bands, int_profile),
    }
