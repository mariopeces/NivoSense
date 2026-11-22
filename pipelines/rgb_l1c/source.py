"""Where the L1C bands are read from: the Sentinel-2 L1C items on Earth Search and the GDAL
settings for each way of reaching their JP2 files."""

import os
from collections.abc import Callable
from datetime import date

from pipelines.s2.stac import Acquisition, Fetch, fetch_json, group_acquisitions, search_items

COLLECTION = "sentinel-2-l1c"
RGB_ASSETS = ("red", "green", "blue")
# The ESA band files behind the Earth Search asset names, used to build CDSE paths.
BAND_FILES = {"red": "B04", "green": "B03", "blue": "B02"}

AWS = "aws"
AWS_REQUESTER_PAYS = "aws-requester-pays"
CDSE = "cdse"
SOURCES = (AWS, AWS_REQUESTER_PAYS, CDSE)

_COMMON = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    # The L2A reader allows only .tif; the L1C bands are JPEG 2000.
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".jp2",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_MAX_RETRY": "4",
    "GDAL_HTTP_RETRY_DELAY": "3",
    # OpenJPEG decodes code blocks on several threads; decoding, not transfer, dominates a read.
    "GDAL_NUM_THREADS": "ALL_CPUS",
}
# s3://sentinel-s2-l1c is the Sentinel-2 L1C bucket of the AWS Registry of Open Data, in Frankfurt.
_AWS_REGION = "eu-central-1"
CDSE_ENDPOINT = "eodata.dataspace.copernicus.eu"


class MissingCredentials(RuntimeError):
    pass


def find_acquisition(
    hull: dict,
    day: date,
    datatake: str,
    touches: Callable[[dict], bool],
    fetch: Fetch = fetch_json,
) -> Acquisition | None:
    """The L1C acquisition of the same datatake as the L2A record (s2:datatake_id without its
    baseline suffix, shared by L1C and L2A of one overpass), from the granules that touch the
    domain, newest processing baseline per tile; None when Earth Search lists none. Matching
    the datatake, not only the orbit, keeps the RGB on the pass the snow mask was made from
    when two satellites cross the same orbit that day."""
    items = [item for item in search_items(hull, day, day, fetch, COLLECTION) if touches(item["geometry"])]
    return next((a for a in group_acquisitions(items) if a.day == day and a.datatake == datatake), None)


def gdal_options(source: str, environ: os._Environ[str] | dict[str, str] = os.environ) -> dict[str, str]:
    """GDAL configuration for reading the JP2 files from `source`.

    `aws` (default) reads s3://sentinel-s2-l1c without signing. `aws-requester-pays` signs with the
    standard AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY that GDAL reads from the environment and
    accepts the transfer charge. `cdse` reads the Copernicus Data Space eodata bucket with the S3
    keys in CDSE_S3_ACCESS_KEY / CDSE_S3_SECRET_KEY. Credentials are passed to GDAL, never logged.
    """
    if source == AWS:
        return {**_COMMON, "AWS_NO_SIGN_REQUEST": "YES", "AWS_REGION": _AWS_REGION}
    if source == AWS_REQUESTER_PAYS:
        if not environ.get("AWS_ACCESS_KEY_ID") or not environ.get("AWS_SECRET_ACCESS_KEY"):
            raise MissingCredentials("aws-requester-pays needs AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
        return {**_COMMON, "AWS_NO_SIGN_REQUEST": "NO", "AWS_REGION": _AWS_REGION, "AWS_REQUEST_PAYER": "requester"}
    if source == CDSE:
        key, secret = environ.get("CDSE_S3_ACCESS_KEY"), environ.get("CDSE_S3_SECRET_KEY")
        if not key or not secret:
            raise MissingCredentials("cdse needs CDSE_S3_ACCESS_KEY and CDSE_S3_SECRET_KEY")
        return {
            **_COMMON,
            "AWS_NO_SIGN_REQUEST": "NO",
            "AWS_S3_ENDPOINT": CDSE_ENDPOINT,
            "AWS_VIRTUAL_HOSTING": "FALSE",
            "AWS_HTTPS": "YES",
            "AWS_ACCESS_KEY_ID": key,
            "AWS_SECRET_ACCESS_KEY": secret,
        }
    raise ValueError(f"Unknown L1C source {source!r}; expected one of {SOURCES}")


def asset_href(item: dict, asset: str, source: str) -> str:
    """GDAL path of one band of one L1C granule."""
    if source in (AWS, AWS_REQUESTER_PAYS):
        href = item["assets"][asset]["href"]
        if not href.startswith("s3://sentinel-s2-l1c/"):
            raise ValueError(f"{item['id']} {asset} is not in s3://sentinel-s2-l1c: {href}")
        return "/vsis3/" + href.removeprefix("s3://")
    if source == CDSE:
        return _cdse_href(item, asset)
    raise ValueError(f"Unknown L1C source {source!r}; expected one of {SOURCES}")


def _cdse_href(item: dict, asset: str) -> str:
    """The band file inside the SAFE product on the CDSE eodata bucket, named by the Sentinel-2
    Products Specification Document: GRANULE/L1C_<tile>_A<abs orbit>_<datastrip start>/IMG_DATA/
    <tile>_<datatake start>_<band>.jp2. The parts come from the STAC properties."""
    properties = item["properties"]
    safe = properties["s2:product_uri"]
    if not safe.endswith(".SAFE"):
        safe += ".SAFE"
    # S2A_MSIL1C_20261110T110211_N0513_R094_T30SVF_20261110T143621.SAFE
    _, _, datatake_start, _, _, tile, _ = safe.removesuffix(".SAFE").split("_")
    # S2A_OPER_MSI_L1C_TL_2APS_20261110T143621_A059465_T30SVF_N05.13
    absolute_orbit = properties["s2:tile_id"].split("_")[-3]
    # S2A_OPER_MSI_L1C_DS_2APS_20261110T143621_S20261110T110234_N05.13
    datastrip_start = properties["s2:datastrip_id"].split("_")[-2].removeprefix("S")
    granule = f"L1C_{tile}_{absolute_orbit}_{datastrip_start}"
    day = datatake_start[:8]
    folder = f"Sentinel-2/MSI/L1C/{day[:4]}/{day[4:6]}/{day[6:8]}/{safe}/GRANULE/{granule}/IMG_DATA"
    return f"/vsis3/eodata/{folder}/{tile}_{datatake_start}_{BAND_FILES[asset]}.jp2"
