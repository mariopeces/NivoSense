import json
from pathlib import Path


def _positions(value):
    if (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
        return
    if isinstance(value, list):
        for item in value:
            yield from _positions(item)


def bbox_from_geojson(path: Path) -> tuple[float, float, float, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    coordinates = []
    if payload.get("type") == "FeatureCollection":
        coordinates = [
            feature.get("geometry", {}).get("coordinates", [])
            for feature in payload.get("features", [])
        ]
    elif payload.get("type") == "Feature":
        coordinates = [payload.get("geometry", {}).get("coordinates", [])]
    else:
        coordinates = [payload.get("coordinates", [])]

    points = [point for geometry in coordinates for point in _positions(geometry)]
    if not points:
        raise ValueError(f"No coordinates found in {path}")
    longitudes, latitudes = zip(*points)
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)
