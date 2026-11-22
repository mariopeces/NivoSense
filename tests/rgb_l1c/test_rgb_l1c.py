import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from pipelines.catalog import LocalStorage
from pipelines.rgb_l1c import qa, render, run, source
from pipelines.s2.domain import Domain, Grid
from pipelines.s2.stac import Acquisition, group_acquisitions

FIXTURE = Path(__file__).parent / "fixtures" / "earth_search_l1c_2026-11-10.json"
# A 20 m grid inside tile 30SVF (tile corner 399960, 4100040), 8 x 6 pixels.
GRID_20 = Grid("EPSG:32630", 450000.0, 4100000.0, 20.0, 8, 6)


def fixture_items() -> list[dict]:
    return [item for page in json.loads(FIXTURE.read_text(encoding="utf-8"))["pages"] for item in page["features"]]


class PagedFetch:
    def __init__(self, pages: list[dict]):
        self.pages = list(pages)
        self.bodies: list[dict] = []

    def __call__(self, request) -> dict:
        self.bodies.append(json.loads(request.data))
        return self.pages.pop(0)


# --- source ---------------------------------------------------------------------------------


def test_finds_the_l1c_acquisition_of_the_date_and_orbit():
    fetch = PagedFetch(json.loads(FIXTURE.read_text(encoding="utf-8"))["pages"])
    hull = {"type": "Polygon", "coordinates": [[[-3.5, 37.0], [-3.0, 37.0], [-3.0, 37.2], [-3.5, 37.0]]]}

    acquisition = source.find_acquisition(hull, date(2026, 11, 10), "R094", lambda geometry: True, fetch)

    assert fetch.bodies[0]["collections"] == ["sentinel-2-l1c"]
    assert fetch.bodies[0]["datetime"] == "2026-11-10T00:00:00Z/2026-11-10T23:59:59Z"
    assert acquisition is not None
    assert acquisition.tiles == ("30SVF", "30SVG", "30SWF", "30SWG")
    assert acquisition.scene_ids[0] == "S2A_30SVF_20261110_1_L1C"


def test_no_acquisition_for_another_orbit_or_untouched_granules():
    pages = json.loads(FIXTURE.read_text(encoding="utf-8"))["pages"]
    hull = {"type": "Point", "coordinates": [-3.3, 37.1]}

    assert source.find_acquisition(hull, date(2026, 11, 10), "R051", lambda g: True, PagedFetch(pages)) is None
    assert source.find_acquisition(hull, date(2026, 11, 10), "R094", lambda g: False, PagedFetch(pages)) is None


def test_aws_reads_unsigned_and_allows_jp2():
    options = source.gdal_options("aws", environ={})

    assert options["AWS_NO_SIGN_REQUEST"] == "YES"
    assert ".jp2" in options["CPL_VSIL_CURL_ALLOWED_EXTENSIONS"]
    assert "AWS_REQUEST_PAYER" not in options


def test_requester_pays_needs_aws_keys_and_accepts_the_charge():
    with pytest.raises(source.MissingCredentials):
        source.gdal_options("aws-requester-pays", environ={})

    options = source.gdal_options(
        "aws-requester-pays", environ={"AWS_ACCESS_KEY_ID": "id", "AWS_SECRET_ACCESS_KEY": "secret"}
    )

    assert options["AWS_REQUEST_PAYER"] == "requester"
    assert options["AWS_NO_SIGN_REQUEST"] == "NO"
    assert "AWS_ACCESS_KEY_ID" not in options


def test_cdse_needs_its_s3_keys_and_points_gdal_at_its_endpoint():
    with pytest.raises(source.MissingCredentials):
        source.gdal_options("cdse", environ={"AWS_ACCESS_KEY_ID": "id", "AWS_SECRET_ACCESS_KEY": "secret"})

    options = source.gdal_options("cdse", environ={"CDSE_S3_ACCESS_KEY": "k", "CDSE_S3_SECRET_KEY": "s"})

    assert options["AWS_S3_ENDPOINT"] == "eodata.dataspace.copernicus.eu"
    assert options["AWS_VIRTUAL_HOSTING"] == "FALSE"
    assert (options["AWS_ACCESS_KEY_ID"], options["AWS_SECRET_ACCESS_KEY"]) == ("k", "s")


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError):
        source.gdal_options("gcs", environ={})


def test_hrefs_per_source():
    item = next(item for item in fixture_items() if item["id"] == "S2A_30SVF_20261110_1_L1C")

    assert source.asset_href(item, "red", "aws") == "/vsis3/sentinel-s2-l1c/tiles/30/S/VF/2026/11/10/1/B04.jp2"
    assert source.asset_href(item, "blue", "aws-requester-pays").endswith("/2026/11/10/1/B02.jp2")
    assert source.asset_href(item, "green", "cdse") == (
        "/vsis3/eodata/Sentinel-2/MSI/L1C/2026/11/10/"
        "S2A_MSIL1C_20261110T110211_N0513_R094_T30SVF_20261110T143621.SAFE/GRANULE/"
        "L1C_T30SVF_A059465_20261110T110234/IMG_DATA/T30SVF_20261110T110211_B03.jp2"
    )


# --- render ---------------------------------------------------------------------------------


def test_10m_grid_nests_in_the_20m_grid():
    grid = render.grid_10m(GRID_20)

    assert (grid.left, grid.top, grid.resolution, grid.width, grid.height) == (450000.0, 4100000.0, 10.0, 16, 12)


def test_stretch_keeps_zero_for_nodata_and_is_monotonic():
    values = np.array([np.nan, -0.05, 0.0, 0.1, 0.5, 1.0, 1.6, 2.0], dtype="float32")

    out = render.stretch(values, black=0.0, white=1.6, gamma=2.2)

    assert out[0] == 0
    assert out[1] == out[2] == 1
    assert out[-2] == out[-1] == 255
    assert np.all(np.diff(out[1:].astype(int)) >= 0)
    assert out[3] == 1 + round(254 * (0.1 / 1.6) ** (1 / 2.2))


def write_tile(path: Path, left: float, top: float, data: np.ndarray) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype="uint16",
        crs="EPSG:32630",
        transform=from_origin(left, top, 10.0, 10.0),
    ) as target:
        target.write(data, 1)


def fake_item(name: str, hrefs: dict[str, str]) -> dict:
    bands = [{"nodata": 0, "data_type": "uint16", "spatial_resolution": 10, "scale": 0.0001, "offset": -0.1}]
    return {"id": name, "assets": {asset: {"href": href, "raster:bands": bands} for asset, href in hrefs.items()}}


def test_reads_and_mosaics_tiles_first_with_data(tmp_path, monkeypatch):
    grid = render.grid_10m(GRID_20)
    # Tile A covers the left 10 columns, tile B the whole grid; A wins where it has data.
    hrefs: dict[str, dict[str, str]] = {"A": {}, "B": {}}
    for asset, dn in (("red", 3000), ("green", 2000), ("blue", 1500)):
        a = np.zeros((grid.height, grid.width), dtype="uint16")
        a[:, :10] = dn
        b = np.full((grid.height, grid.width), dn + 100, dtype="uint16")
        for name, data in (("A", a), ("B", b)):
            path = tmp_path / f"{name}_{asset}.tif"
            write_tile(path, grid.left, grid.top, data)
            hrefs[name][asset] = str(path)
    acquisition = Acquisition(date(2026, 11, 10), "R094", (fake_item("A", hrefs["A"]), fake_item("B", hrefs["B"])))
    monkeypatch.setattr(render, "asset_href", lambda item, asset, src: item["assets"][asset]["href"])

    reflectance = render.read_reflectance(acquisition, grid, "aws")

    np.testing.assert_allclose(reflectance["red"][:, :10], 0.2, atol=1e-6)
    np.testing.assert_allclose(reflectance["red"][:, 10:], 0.21, atol=1e-6)
    np.testing.assert_allclose(reflectance["blue"][:, 10:], 0.06, atol=1e-6)


def test_misaligned_tile_is_rejected(tmp_path, monkeypatch):
    grid = render.grid_10m(GRID_20)
    hrefs = {}
    for asset in ("red", "green", "blue"):
        path = tmp_path / f"{asset}.tif"
        write_tile(path, grid.left + 5, grid.top, np.ones((grid.height, grid.width), dtype="uint16"))
        hrefs[asset] = str(path)
    acquisition = Acquisition(date(2026, 11, 10), "R094", (fake_item("A", hrefs),))
    monkeypatch.setattr(render, "asset_href", lambda item, asset, src: item["assets"][asset]["href"])

    with pytest.raises(ValueError, match="not aligned"):
        render.read_reflectance(acquisition, grid, "aws")


def test_render_crops_to_the_domain_and_marks_missing_bands():
    shape = (4, 4)
    reflectance = {asset: np.full(shape, 0.3, dtype="float32") for asset in ("red", "green", "blue")}
    reflectance["blue"][0, 0] = np.nan
    inside = np.ones(shape, dtype=bool)
    inside[3, 3] = False

    rgb = render.render(reflectance, inside)

    assert rgb.shape == (3, 4, 4)
    assert (rgb[:, 0, 0] == 0).all() and (rgb[:, 3, 3] == 0).all()
    assert (rgb[:, 1, 1] > 0).all()


# --- qa -------------------------------------------------------------------------------------


def test_snow_stand_in_is_lis_pass_one_on_clear_pixels():
    reflectance = {
        "green": np.array([[0.8, 0.8, 0.8, 0.3]], dtype="float32"),
        "red": np.array([[0.7, 0.7, 0.15, 0.3]], dtype="float32"),
        "swir16": np.array([[0.1, 0.1, 0.1, 0.25]], dtype="float32"),
    }
    scl = np.array([[11, 9, 4, 4]], dtype="uint8")

    assert qa.snow_mask(reflectance, scl).tolist() == [[True, False, False, False]]


def test_snow_saturation_counts_10m_pixels_under_20m_snow():
    snow = np.array([[True, False]])
    rgb = np.full((3, 2, 4), 200, dtype="uint8")
    rgb[:, 0, 0] = 255
    rgb[0, 1, 1] = 255

    scores = qa.snow_saturation(rgb, snow)

    assert scores["snow_pixels_10m"] == 4
    assert scores["snow_saturated_red"] == 0.5
    assert scores["snow_saturated_green"] == 0.25
    assert scores["snow_saturated_all"] == 0.25


def smooth_noise(shape: tuple[int, int], seed: int = 0) -> np.ndarray:
    """Random texture with a few pixels of correlation length, like terrain."""
    rng = np.random.default_rng(seed)
    noise = rng.random((shape[0] + 8, shape[1] + 8))
    kernel = np.ones(5) / 5
    noise = np.apply_along_axis(lambda row: np.convolve(row, kernel, "same"), 1, noise)
    noise = np.apply_along_axis(lambda col: np.convolve(col, kernel, "same"), 0, noise)
    return noise[4 : 4 + shape[0], 4 : 4 + shape[1]].astype("float32")


def test_phase_shift_recovers_a_known_displacement():
    image = smooth_noise((300, 300))
    reference = image[20:276, 20:276]
    moving = image[17:273, 22:278]

    rows, cols = qa.phase_shift(reference, moving)

    assert rows == pytest.approx(3, abs=0.2)
    assert cols == pytest.approx(-2, abs=0.2)


def rgb_from_20m(green20: np.ndarray) -> np.ndarray:
    band = np.clip(np.repeat(np.repeat(green20, 2, axis=0), 2, axis=1) * 254 + 1, 1, 255).astype("uint8")
    return np.stack([band, band, band])


def test_alignment_is_zero_on_aligned_data_and_flags_a_shift():
    image = smooth_noise((600, 600))
    green = image[:512, :512]
    snow = green > np.median(green)
    l2a = {"green": green}

    aligned = qa.alignment(rgb_from_20m(green), l2a, snow, 20.0)
    shifted = qa.alignment(rgb_from_20m(image[2:514, :512]), l2a, snow, 20.0)

    assert aligned["shift_l2a_green_chips"] == 4
    assert aligned["shift_l2a_green_max_m"] < 2
    assert aligned["shift_snow_mask_max_m"] < 2
    assert shifted["shift_l2a_green_median_m"] == pytest.approx(40, abs=4)
    assert shifted["shift_snow_mask_median_m"] == pytest.approx(40, abs=4)
    assert aligned["shift_l2a_green_within_20m"] == 1
    assert shifted["shift_l2a_green_within_20m"] == 0


# --- run ------------------------------------------------------------------------------------


def write_record(out: Path, day: str, orbit: str, listed: bool, valid: float, tiles: list[str]) -> Path:
    folder = out / day / orbit
    folder.mkdir(parents=True)
    record = {"date": day, "orbit": orbit, "listed": listed, "domain_valid_fraction": valid, "tiles": tiles}
    (folder / "record.json").write_text(json.dumps(record), encoding="utf-8")
    return folder


def test_observation_dates_take_listed_records_and_the_best_orbit(tmp_path):
    write_record(tmp_path, "2026-11-10", "R051", True, 0.4, ["30SWG"])
    write_record(tmp_path, "2026-11-10", "R094", True, 0.8, ["30SVF"])
    write_record(tmp_path, "2026-11-12", "R094", False, 0.1, ["30SVF"])
    write_record(tmp_path, "2026-11-25", "R094", True, 0.9, ["30SVF"])

    records = run.observation_dates(tmp_path, date(2026, 11, 1), date(2026, 11, 21))

    assert [(r["date"], r["orbit"]) for r in records] == [("2026-11-10", "R094")]


def write_l2a(folder: Path, grid: Grid, green: np.ndarray, snow: np.ndarray) -> None:
    profile = {
        "driver": "GTiff",
        "width": grid.width,
        "height": grid.height,
        "crs": grid.crs,
        "transform": grid.transform,
    }
    red = np.where(snow, 0.7, 0.1).astype("float32")
    swir = np.where(snow, 0.05, 0.2).astype("float32")
    with rasterio.open(folder / "reflectance.tif", "w", count=3, dtype="float32", **profile) as target:
        for band, (name, data) in enumerate((("green", green), ("red", red), ("swir16", swir)), start=1):
            target.write(data.astype("float32"), band)
            target.set_band_description(band, name)
    with rasterio.open(folder / "classes.tif", "w", count=2, dtype="uint8", **profile) as target:
        target.write(np.where(snow, 11, 4).astype("uint8"), 1)
        target.write(np.zeros(green.shape, dtype="uint8"), 2)


def test_process_publishes_through_the_catalogue_and_logs_missing_l1c(tmp_path, monkeypatch):
    grid20 = Grid("EPSG:32630", 450000.0, 4100000.0, 20.0, 64, 48)
    domain = Domain((), grid20, np.ones((48, 64), dtype=bool))
    grid10 = render.grid_10m(grid20)
    inside = np.ones((grid10.height, grid10.width), dtype=bool)
    green20 = smooth_noise((48, 64))
    snow = green20 > 0.5
    s2_out = tmp_path / "s2"
    record = {
        "date": "2026-11-10",
        "orbit": "R094",
        "tiles": ["30SVF", "30SVG"],
        "listed": True,
        "domain_valid_fraction": 0.8,
    }
    write_l2a(write_record(s2_out, "2026-11-10", "R094", True, 0.8, record["tiles"]), grid20, green20, snow)
    l1c = [i for i in group_acquisitions(fixture_items()) if i.orbit == "R094"][0]
    acquisition = Acquisition(l1c.day, l1c.orbit, tuple(i for i in l1c.items if "30SVF" in i["id"]))
    up = np.repeat(np.repeat(green20, 2, axis=0), 2, axis=1).astype("float32")
    monkeypatch.setattr(run, "find_acquisition", lambda *args: acquisition)
    monkeypatch.setattr(run, "read_reflectance", lambda *args: {"red": up, "green": up, "blue": up})
    monkeypatch.setattr(run, "code_version", lambda: "test")
    storage = LocalStorage(tmp_path / "catalog")

    result = run.process(record, domain, {}, inside, s2_out, storage, "aws")

    assert result["status"] == "published"
    assert result["l1c_missing_tiles"] == ["30SVG"]
    assert "l1c_tiles_missing" in result["qa"]["flags"]
    entry = json.loads(storage.read("catalog/entries/rgb/2026-11-10.json").data)
    assert entry["source_ids"] == ["S2A_30SVF_20261110_1_L1C"]
    assert entry["resolution_m"] == 10 and entry["value_range"] == [[1, 255]] * 3
    assert entry["qa"]["scores"]["snow_saturated_all"] == 0
    with rasterio.open(storage.root / entry["cog"]) as cog:
        assert (cog.count, cog.dtypes[0], cog.nodata, cog.res) == (3, "uint8", 0, (10.0, 10.0))

    monkeypatch.setattr(run, "find_acquisition", lambda *args: None)
    assert run.process(record, domain, {}, inside, s2_out, storage, "aws")["status"] == "l1c_missing"


def test_qa_flags():
    clean = {"snow_saturated_red": 0.002, "shift_l2a_green_median_m": 0.1}

    assert run.qa_flags(clean, []) == []
    assert run.qa_flags({**clean, "snow_saturated_blue": 0.01}, []) == ["snow_saturated"]
    assert run.qa_flags({**clean, "shift_l2a_green_median_m": 20.0}, ["30SVG"]) == ["l1c_tiles_missing", "misaligned"]
