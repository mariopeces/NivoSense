from datetime import date

from pipelines.s2.stac import COLLECTION, LEGACY_COLLECTION, search_merged
from pipelines.snow_obs import run as snow_obs


def item(collection: str, tile: str, datatake: str, href: str) -> dict:
    return {
        "id": f"{collection}-{tile}-{datatake}",
        "collection": collection,
        "assets": {"green": {"href": href}},
        "properties": {
            "mgrs:utm_zone": 30,
            "mgrs:latitude_band": "S",
            "mgrs:grid_square": tile,
            "s2:datatake_id": datatake,
        },
    }


COG = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/x/B03.tif"
JP2 = "s3://sentinel-s2-l2a/tiles/30/S/VF/2021/2/17/1/R10m/B03.jp2"


def fake_fetch_for(c1: list[dict], legacy: list[dict]):
    def fetch(request) -> dict:
        import json

        collection = json.loads(request.data)["collections"][0]
        return {"features": c1 if collection == COLLECTION else legacy, "links": []}

    return fetch


def test_merged_search_adds_only_cog_legacy_items_that_c1_lacks():
    c1 = [item(COLLECTION, "VF", "GS2A_20210217T110000_029000", COG)]
    legacy = [
        item(LEGACY_COLLECTION, "VF", "GS2A_20210217T110000_029000", COG),  # c1 has the granule
        item(LEGACY_COLLECTION, "VG", "GS2A_20210217T110000_029000", COG),  # only legacy has it
        item(LEGACY_COLLECTION, "WG", "GS2A_20210217T110000_029000", JP2),  # no COGs
        item(LEGACY_COLLECTION, "VG", "GS2A_20210222T110000_029100", COG),  # another datatake
    ]
    merged = search_merged({}, date(2021, 2, 17), date(2021, 2, 22), fake_fetch_for(c1, legacy))
    assert [(i["collection"], i["properties"]["mgrs:grid_square"]) for i in merged] == [
        (COLLECTION, "VF"),
        (LEGACY_COLLECTION, "VG"),
        (LEGACY_COLLECTION, "VG"),
    ]


def test_sun_angles_ask_each_scene_in_its_own_collection():
    asked = []

    def fetch(request) -> dict:
        asked.append(request.full_url)
        return {"properties": {"view:sun_azimuth": 150.0, "view:sun_elevation": 30.0}}

    snow_obs.sun_angles(["a", "b"], fetch, [COLLECTION, LEGACY_COLLECTION])
    assert asked[0].endswith(f"/collections/{COLLECTION}/items/a")
    assert asked[1].endswith(f"/collections/{LEGACY_COLLECTION}/items/b")
