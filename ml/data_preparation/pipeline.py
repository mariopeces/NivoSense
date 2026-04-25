"""
End-to-end data preparation for one Sentinel-2 acquisition.

Bands are downloaded locally via the GCS Python client (not GDAL streaming)
to avoid /vsigs/ hanging on slow connections. Temp files are cleaned up
automatically. Output is a 5-band COG uploaded to nivosense-cogs.

Bands in output COG:
  1  ndsi               float32   cloud-masked NDSI [−1, 1]
  2  elevation_m        float32   metres
  3  slope_deg          float32   degrees [0, 90]
  4  aspect_deg         float32   degrees from North [0, 360)
  5  elevation_band     float32   discrete band index (200 m intervals)
"""
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles
from google.cloud import storage

from .ndsi import compute_ndsi
from .dem import load_dem_layers
from .align import get_reference_grid, align_to_grid

_SRC_BUCKET  = "darwin-general-hdh-sandbox-tiles"
_SRC_PREFIX  = "tiles/guest/raster/temporal/s2_raw_images"
_OUT_BUCKET  = "nivosense-cogs"
_OUT_PREFIX  = "observations/sierra-nevada"


def _download_band(bucket, year: int, month: str, band: str, timestamp: str, dest: Path) -> None:
    blob_name = (
        f"{_SRC_PREFIX}/{year}/{month}/"
        f"s2_raw_images_{band}_{year}_{month}_sierra_nevada_{timestamp}.tif"
    )
    bucket.blob(blob_name).download_to_filename(str(dest))


def prepare_acquisition(
    year: int,
    month: str,
    timestamp: str,
    dem_path: str,
    elevation_band_interval_m: float = 200.0,
) -> str:
    """
    Download S2 bands, compute features, write COG, upload to GCS.

    Returns the gs:// URI of the uploaded COG.
    """
    client = storage.Client()
    src_bucket = client.bucket(_SRC_BUCKET)

    gcs_blob_path = f"{_OUT_PREFIX}/{year}/{month}/ndsi_{year}_{month}_{timestamp}.tif"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 1. Download bands locally — avoids GDAL /vsigs/ streaming hangs
        _download_band(src_bucket, year, month, "b03", timestamp, tmp / "b03.tif")
        _download_band(src_bucket, year, month, "b11", timestamp, tmp / "b11.tif")
        _download_band(src_bucket, year, month, "scl", timestamp, tmp / "scl.tif")

        # 2. NDSI + cloud mask
        ndsi, ndsi_profile = compute_ndsi(
            str(tmp / "b03.tif"),
            str(tmp / "b11.tif"),
            str(tmp / "scl.tif"),
        )

        # 3. Reference grid from B03 (10 m, UTM)
        ref_grid = get_reference_grid(str(tmp / "b03.tif"))

        # 4. DEM layers (5 m → 10 m)
        dem_layers = load_dem_layers(dem_path, interval_m=elevation_band_interval_m)
        aligned = {}
        for name, (arr, prof) in dem_layers.items():
            resamp = Resampling.nearest if name == "elevation_bands" else Resampling.bilinear
            aligned[name], _ = align_to_grid(arr, prof, ref_grid, resampling=resamp)

        # 5. Write raw GeoTIFF
        out_profile = ndsi_profile.copy()
        out_profile.update(count=5, dtype="float32", compress="deflate", nodata=np.nan)

        raw_path = tmp / "raw.tif"
        cog_path = tmp / "cog.tif"

        with rasterio.open(raw_path, "w", **out_profile) as dst:
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

        # 6. Convert to COG
        cog_translate(raw_path, cog_path, cog_profiles.get("deflate"), overview_level=4, quiet=True)

        # 7. Upload
        client.bucket(_OUT_BUCKET).blob(gcs_blob_path).upload_from_filename(
            str(cog_path), content_type="image/tiff"
        )

    return f"gs://{_OUT_BUCKET}/{gcs_blob_path}"
