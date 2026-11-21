import copy
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform

from pipelines.s2 import ingest
from pipelines.s2.domain import Grid, convex_hull, load_domain
from pipelines.s2.mosaic import build_mosaic, domain_fractions, read_window, scale_offset, to_grid_reflectance
from pipelines.s2.stac import COLLECTION, expected_tiles, group_acquisitions, orbit_of, search_items

FIXTURE = Path(__file__).parent / "fixtures" / "earth_search_2026-11-05_10.json"


def fixture_pages() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["pages"]


def fixture_items() -> list[dict]:
    return [item for page in fixture_pages() for item in page["features"]]


class PagedFetch:
    """Serves the recorded Earth Search pages in order and keeps the request bodies."""

    def __init__(self, pages: list[dict]):
        self.pages = list(pages)
        self.bodies: list[dict] = []

    def __call__(self, request) -> dict:
        self.bodies.append(json.loads(request.data))
        return self.pages.pop(0)


def test_search_follows_post_pages_and_sends_the_geometry():
    fetch = PagedFetch(fixture_pages())
    hull = {"type": "Polygon", "coordinates": [[[-3.5, 37.0], [-3.0, 37.0], [-3.0, 37.2], [-3.5, 37.0]]]}

    items = search_items(hull, date(2026, 11, 5), date(2026, 11, 10), fetch)

    assert len(items) == 17
    assert fetch.bodies[0]["collections"] == [COLLECTION]
    assert fetch.bodies[0]["intersects"] == hull
    assert fetch.bodies[0]["datetime"] == "2026-11-05T00:00:00Z/2026-11-10T23:59:59Z"
    assert "eo:cloud_cover" not in json.dumps(fetch.bodies[0])
    assert len(fetch.bodies) == 3


def test_real_items_group_by_date_and_orbit():
    acquisitions = group_acquisitions(fixture_items())

    assert [(a.day.isoformat(), a.orbit, a.tiles) for a in acquisitions] == [
        ("2026-11-05", "R051", ("30SVF", "30SWF", "30SWG")),
        ("2026-11-07", "R051", ("30SVF", "30SWF", "30SWG")),
        ("2026-11-08", "R094", ("30SVF", "30SVG", "30SWF", "30SWG")),
        ("2026-11-10", "R051", ("30SVF", "30SWF", "30SWG")),
        ("2026-11-10", "R094", ("30SVF", "30SVG", "30SWF", "30SWG")),
    ]
    assert expected_tiles(acquisitions) == {
        "R051": {"30SVF", "30SWF", "30SWG"},
        "R094": {"30SVF", "30SVG", "30SWF", "30SWG"},
    }


def test_reprocessed_granule_replaces_the_older_one():
    items = fixture_items()
    newer = copy.deepcopy(next(i for i in items if i["id"] == "S2A_T30SVF_20261110T110234_L2A"))
    newer["id"] = "reprocessed"
    newer["properties"]["s2:processing_baseline"] = "05.14"

    acquisition = next(a for a in group_acquisitions(items + [newer]) if a.orbit == "R094" and a.day.day == 10)

    assert acquisition.scene_ids.count("reprocessed") == 1
    assert "S2A_T30SVF_20261110T110234_L2A" not in acquisition.scene_ids


def test_split_granules_of_one_tile_are_all_kept_latest_first():
    items = fixture_items()
    original = next(i for i in items if i["id"] == "S2B_T30SWG_20261110T105459_L2A")
    split = copy.deepcopy(original)
    split["id"] = "second-part"
    split["properties"]["s2:generation_time"] = "2026-11-10T18:00:00.000000Z"

    acquisition = next(a for a in group_acquisitions(items + [split]) if a.orbit == "R051" and a.day.day == 10)

    assert acquisition.tiles == ("30SVF", "30SWF", "30SWG")
    assert acquisition.scene_ids[-2:] == ("second-part", "S2B_T30SWG_20261110T105459_L2A")


def test_only_footprints_that_touch_the_domain_count():
    domain = load_domain(Path(__file__).parents[2] / "data" / "basins.geojson")
    touching = {i["id"] for i in fixture_items() if domain.touches(i["geometry"])}
    # Orbit R051 reaches the domain only through 30SWG; its 30SVF and 30SWF granules
    # intersect the search hull but not the polygons.
    assert "S2B_T30SWG_20261110T105459_L2A" in touching
    assert "S2B_T30SVF_20261110T105459_L2A" not in touching
    assert "S2B_T30SWF_20261110T105459_L2A" not in touching
    assert {i for i in touching if i.startswith("S2A_T30S") and "20261110" in i} == {
        "S2A_T30SVF_20261110T110234_L2A",
        "S2A_T30SVG_20261110T110234_L2A",
        "S2A_T30SWF_20261110T110234_L2A",
        "S2A_T30SWG_20261110T110234_L2A",
    }


def test_item_without_orbit_in_product_name_is_rejected():
    item = copy.deepcopy(fixture_items()[0])
    item["properties"]["s2:product_uri"] = "S2A_MSIL2A_20261110T110211_N0513_T30SVF"
    with pytest.raises(ValueError, match="relative orbit"):
        orbit_of(item)


def test_convex_hull_keeps_outer_vertices_only():
    square = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [1, 1], [0, 2], [0, 0]]]}
    hull = convex_hull((square,))
    assert sorted(map(tuple, hull["coordinates"][0][:-1])) == [(0, 0), (0, 2), (2, 0), (2, 2)]
    assert hull["coordinates"][0][0] == hull["coordinates"][0][-1]


def test_scale_and_offset_come_from_raster_bands():
    item = fixture_items()[0]
    assert scale_offset(item, "green") == (0.0001, -0.1)
    broken = copy.deepcopy(item)
    del broken["assets"]["green"]["raster:bands"][0]["offset"]
    with pytest.raises(ValueError, match="scale and offset"):
        scale_offset(broken, "green")


def test_10m_band_is_averaged_and_nodata_blocks_stay_nodata():
    raw = np.array([[2000, 2200, 0, 3000], [2400, 2600, 3000, 3000]], dtype="uint16")
    values = to_grid_reflectance(raw, 0.0001, -0.1, 2)
    assert values.shape == (1, 2)
    assert values[0, 0] == pytest.approx(0.13)
    assert math.isnan(values[0, 1])


def test_domain_fractions_count_only_clear_classes_inside_the_domain():
    scl = np.array([[0, 4, 8, 11], [3, 5, 2, 9]], dtype="uint8")
    mask = np.array([[True, True, True, True], [True, True, True, False]])
    coverage, valid = domain_fractions(scl, mask)
    assert coverage == pytest.approx(6 / 7)
    assert valid == pytest.approx(4 / 7)


# Offline rasters for the read and mosaic path: tiny tiles in EPSG:32630 west of the Veleta,
# where the real 30SVF and 30SVG footprints overlap, on the 20 m pixel lattice of UTM zone 30.
TILE_LEFT, TILE_TOP, TILE_SIZE_M = 460000.0, 4098000.0, 2000


def write_tile(folder: Path, name: str, pixel: int, value: int, dtype: str, nodata_left_half: bool = False) -> str:
    size = TILE_SIZE_M // pixel
    data = np.full((size, size), value, dtype=dtype)
    if nodata_left_half:
        data[:, : size // 2] = 0
    path = folder / f"{name}.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype=dtype,
        crs="EPSG:32630",
        transform=from_origin(TILE_LEFT, TILE_TOP, pixel, pixel),
        nodata=0,
    ) as target:
        target.write(data, 1)
    return str(path)


def localise(item: dict, folder: Path, scl: int, green: int, nodata_left_half: bool = False) -> dict:
    local = copy.deepcopy(item)
    specs = {
        "green": (10, green, "uint16"),
        "red": (10, 1500, "uint16"),
        "swir16": (20, 1100, "uint16"),
        "scl": (20, scl, "uint8"),
        "cloud": (20, 7, "uint8"),
    }
    for asset, (pixel, value, dtype) in specs.items():
        local["assets"][asset]["href"] = write_tile(
            folder, f"{local['id']}-{asset}", pixel, value, dtype, nodata_left_half
        )
    return local


def small_domain(folder: Path) -> Path:
    xs = [TILE_LEFT + 500, TILE_LEFT + 1500, TILE_LEFT + 1500, TILE_LEFT + 500]
    ys = [TILE_TOP - 500, TILE_TOP - 500, TILE_TOP - 1500, TILE_TOP - 1500]
    lons, lats = transform("EPSG:32630", "EPSG:4326", xs, ys)
    ring = [[lon, lat] for lon, lat in zip(lons, lats)]
    path = folder / "domain.geojson"
    path.write_text(json.dumps({"type": "Polygon", "coordinates": [ring + [ring[0]]]}), encoding="utf-8")
    return path


def test_grid_is_on_the_20m_lattice_and_mask_covers_the_polygon(tmp_path):
    domain = load_domain(small_domain(tmp_path))
    assert domain.grid.crs == "EPSG:32630"
    assert domain.grid.left % 20 == 0 and domain.grid.top % 20 == 0
    assert domain.pixel_count == pytest.approx(50 * 50, rel=0.05)


def test_read_window_rejects_a_grid_off_the_pixel_lattice(tmp_path):
    href = write_tile(tmp_path, "scl", 20, 4, "uint8")
    with pytest.raises(ValueError, match="aligned"):
        read_window(href, Grid("EPSG:32630", TILE_LEFT + 10, TILE_TOP, 20.0, 10, 10))


def test_mosaic_applies_offset_and_fills_from_the_next_tile(tmp_path):
    ids = ("S2A_T30SVF_20261110T110234_L2A", "S2A_T30SWF_20261110T110234_L2A")
    items = [i for i in fixture_items() if i["id"] in ids]
    first = localise(items[0], tmp_path, scl=4, green=2000, nodata_left_half=True)
    second = localise(items[1], tmp_path, scl=8, green=3000)
    acquisition = group_acquisitions([first, second])[0]
    grid = Grid("EPSG:32630", TILE_LEFT, TILE_TOP, 20.0, 100, 100)

    mosaic = build_mosaic(acquisition, grid)

    assert acquisition.tiles == ("30SVF", "30SWF")
    assert np.all(mosaic.scl[:, :50] == 8)
    assert np.all(mosaic.scl[:, 50:] == 4)
    assert np.allclose(mosaic.reflectance["green"][:, 50:], 2000 * 0.0001 - 0.1)
    assert np.allclose(mosaic.reflectance["green"][:, :50], 3000 * 0.0001 - 0.1)
    assert np.allclose(mosaic.reflectance["swir16"], 1100 * 0.0001 - 0.1)
    assert np.all(mosaic.cloud == 7)


def run_offline(tmp_path: Path, items: list[dict], today: date) -> list[dict]:
    pages = [{"type": "FeatureCollection", "features": items, "links": []}]
    return ingest.run(
        small_domain(tmp_path),
        date(2026, 11, 10),
        date(2026, 11, 10),
        tmp_path / "out",
        today,
        fetch=lambda request: copy.deepcopy(pages[0]),
    )


def test_incomplete_date_is_reprocessed_when_the_missing_tile_arrives(tmp_path):
    rasters = tmp_path / "rasters"
    rasters.mkdir()
    items = [localise(i, rasters, scl=4, green=2000) for i in fixture_items()]
    late_tile = "S2A_T30SVG_20261110T110234_L2A"
    early = [i for i in items if i["id"] != late_tile]

    first = run_offline(tmp_path, early, today=date(2026, 11, 10))
    r094 = next(r for r in first if r["orbit"] == "R094")
    assert r094["complete"] is False
    assert r094["missing_tiles"] == ["30SVG"]

    # A later run over a later day still picks up the pending date.
    later = ingest.run(
        small_domain(tmp_path),
        date(2026, 11, 12),
        date(2026, 11, 12),
        tmp_path / "out",
        date(2026, 11, 12),
        fetch=lambda request: {"type": "FeatureCollection", "features": copy.deepcopy(items), "links": []},
    )
    r094 = next(r for r in later if r["orbit"] == "R094" and r["date"] == "2026-11-10")
    assert r094["complete"] is True
    assert late_tile in r094["scene_ids"]
    assert r094["domain_coverage"] == 1.0
    assert r094["domain_valid_fraction"] == 1.0
    assert r094["listed"] is True
    with rasterio.open(tmp_path / "out" / "2026-11-10" / "R094" / "reflectance.tif") as stored:
        assert stored.crs.to_epsg() == 32630
        assert [stored.descriptions[i] for i in range(3)] == ["green", "red", "swir16"]


def test_complete_unchanged_date_is_not_rebuilt(tmp_path, monkeypatch):
    rasters = tmp_path / "rasters"
    rasters.mkdir()
    items = [localise(i, rasters, scl=9, green=2000) for i in fixture_items()]
    records = run_offline(tmp_path, items, today=date(2026, 11, 10))
    assert all(r["complete"] for r in records)
    assert all(r["listed"] is False and r["domain_valid_fraction"] == 0.0 for r in records)

    def fail(*args):
        raise AssertionError("rebuilt a current record")

    monkeypatch.setattr(ingest, "process", fail)
    assert run_offline(tmp_path, items, today=date(2026, 11, 11)) == records


def test_incomplete_dates_past_the_retry_window_are_left_alone(tmp_path):
    folder = tmp_path / "2026-10-01" / "R094"
    folder.mkdir(parents=True)
    (folder / "record.json").write_text(json.dumps({"date": "2026-10-01", "complete": False}), encoding="utf-8")
    assert ingest.pending_start(tmp_path, date(2026, 10, 5)) == date(2026, 10, 1)
    assert ingest.pending_start(tmp_path, date(2026, 11, 1)) is None
