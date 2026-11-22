import json
import re
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-c1-l2a"
PAGE_LIMIT = 100

# Earth Search c1 items carry no sat:relative_orbit; the orbit is in the ESA product name,
# e.g. S2A_MSIL2A_20261110T110211_N0513_R094_T30SVF_20261110T160053.
_ORBIT = re.compile(r"_R(\d{3})_")
# s2:datatake_id ends with the processing baseline (GS2A_20261110T110211_059465_N05.13);
# without it the id names one overpass of one satellite.
_BASELINE_SUFFIX = re.compile(r"_N\d{2}\.\d{2}$")

Fetch = Callable[[urllib.request.Request], dict]


@dataclass(frozen=True)
class Acquisition:
    """The granules of one overpass of one satellite (one datatake) over the domain."""

    day: date
    orbit: str
    datatake: str
    items: tuple[dict, ...]

    @property
    def tiles(self) -> tuple[str, ...]:
        return tuple(sorted({tile_of(item) for item in self.items}))

    @property
    def scene_ids(self) -> tuple[str, ...]:
        return tuple(item["id"] for item in self.items)


def fetch_json(request: urllib.request.Request) -> dict:
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def tile_of(item: dict) -> str:
    properties = item["properties"]
    return f"{properties['mgrs:utm_zone']}{properties['mgrs:latitude_band']}{properties['mgrs:grid_square']}"


def orbit_of(item: dict) -> str:
    match = _ORBIT.search(item["properties"]["s2:product_uri"])
    if match is None:
        raise ValueError(f"No relative orbit in product name of {item['id']}")
    return f"R{match.group(1)}"


def datatake_of(item: dict) -> str:
    return _BASELINE_SUFFIX.sub("", item["properties"]["s2:datatake_id"])


def search_items(geometry: dict, start: date, end: date, fetch: Fetch = fetch_json) -> list[dict]:
    """Every L2A item intersecting the geometry with a UTC acquisition date in [start, end]."""
    body: dict[str, Any] | None = {
        "collections": [COLLECTION],
        "intersects": geometry,
        "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
        "limit": PAGE_LIMIT,
    }
    url = STAC_SEARCH_URL
    items: list[dict] = []
    while body is not None:
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        page = fetch(request)
        items.extend(page["features"])
        next_link = next((link for link in page.get("links", []) if link["rel"] == "next"), None)
        if next_link is None:
            body = None
        elif next_link.get("method", "GET") == "POST":
            url, body = next_link["href"], next_link["body"]
        else:
            raise ValueError("Earth Search returned a GET next link; this client only follows POST")
    return items


def _baseline(item: dict) -> float:
    return float(item["properties"]["s2:processing_baseline"])


def _latest_baseline(granules: list[dict]) -> list[dict]:
    """Granules of the highest processing baseline. One datatake can come as several
    granules of the same tile (2026-11-17, 30SWG: two datastrips generated 67 min apart, the
    later one covering half the pixels of the earlier), so the latest generation is not
    always the most complete: every granule of that baseline is kept and mosaicked."""
    newest = max(_baseline(item) for item in granules)
    return [item for item in granules if _baseline(item) == newest]


def group_acquisitions(items: list[dict]) -> list[Acquisition]:
    """Items grouped by UTC date, relative orbit and datatake, older processing baselines
    dropped, granules ordered by tile name and then latest generation first. Two satellites
    can pass one relative orbit minutes apart (S2A and S2B, 2026-02-13 R051) with different
    clouds; they stay separate acquisitions."""
    granules: dict[tuple[date, str, str, str], list[dict]] = defaultdict(list)
    for item in items:
        day = date.fromisoformat(item["properties"]["datetime"][:10])
        granules[(day, orbit_of(item), datatake_of(item), tile_of(item))].append(item)
    groups: dict[tuple[date, str, str], list[dict]] = defaultdict(list)
    for (day, orbit, datatake, _tile), versions in granules.items():
        groups[(day, orbit, datatake)].extend(_latest_baseline(versions))

    def ordered(group: list[dict]) -> tuple[dict, ...]:
        latest_first = sorted(group, key=lambda item: item["properties"]["s2:generation_time"], reverse=True)
        return tuple(sorted(latest_first, key=tile_of))

    return [
        Acquisition(day, orbit, datatake, ordered(group)) for (day, orbit, datatake), group in sorted(groups.items())
    ]


def expected_tiles(acquisitions: list[Acquisition]) -> dict[str, set[str]]:
    """Per relative orbit, every tile seen on that orbit among items that touch the domain.
    The swath of a relative orbit is fixed, so a tile seen once on an orbit is expected on
    every pass of that orbit."""
    tiles: dict[str, set[str]] = defaultdict(set)
    for acquisition in acquisitions:
        tiles[acquisition.orbit].update(acquisition.tiles)
    return dict(tiles)


def reference_window(start: date, end: date, days: int) -> tuple[date, date]:
    """At least `days` days ending at `end`, so every orbit has passed several times
    (Sentinel-2 repeats each relative orbit every 10 days per satellite)."""
    return min(start, end - timedelta(days=days - 1)), end
