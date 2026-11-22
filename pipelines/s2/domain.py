import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

CRS = "EPSG:32630"
RESOLUTION_M = 20.0


@dataclass(frozen=True)
class Grid:
    crs: str
    left: float
    top: float
    resolution: float
    width: int
    height: int

    @property
    def transform(self) -> Any:
        from rasterio.transform import from_origin

        return from_origin(self.left, self.top, self.resolution, self.resolution)


@dataclass(frozen=True)
class Domain:
    geometries: tuple[dict, ...]
    grid: Grid
    mask: np.ndarray

    @property
    def pixel_count(self) -> int:
        return int(self.mask.sum())

    def touches(self, geometry: dict) -> bool:
        """Whether a footprint (GeoJSON, EPSG:4326) overlaps at least one domain pixel."""
        from rasterio.features import rasterize
        from rasterio.warp import transform_geom

        footprint = rasterize(
            [(transform_geom("EPSG:4326", self.grid.crs, geometry), 1)],
            out_shape=self.mask.shape,
            transform=self.grid.transform,
            fill=0,
            all_touched=True,
            dtype="uint8",
        ).astype(bool)
        return bool((footprint & self.mask).any())


def _polygons(geometry: dict) -> list[list]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return list(geometry["coordinates"])
    raise ValueError(f"Domain geometry must be polygonal, got {geometry['type']}")


def read_geometries(path: Path) -> tuple[dict, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") == "FeatureCollection":
        geometries = [feature["geometry"] for feature in payload["features"]]
    elif payload.get("type") == "Feature":
        geometries = [payload["geometry"]]
    else:
        geometries = [payload]
    for geometry in geometries:
        _polygons(geometry)
    if not geometries:
        raise ValueError(f"No geometry in {path}")
    return tuple(geometries)


def convex_hull(geometries: tuple[dict, ...]) -> dict:
    """GeoJSON polygon of the convex hull of every outer ring vertex (Andrew's monotone chain).

    The STAC search uses the hull because the full domain has tens of thousands of vertices;
    the hull contains the domain, so no intersecting item is missed, and the exact polygon
    decides coverage at pixel level.
    """
    points = sorted(
        {(float(x), float(y)) for geometry in geometries for polygon in _polygons(geometry) for x, y, *_ in polygon[0]}
    )
    if len(points) < 3:
        raise ValueError("Domain needs at least three distinct vertices")

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    ring = lower[:-1] + upper[:-1]
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [[list(point) for point in ring]]}


def build_grid(geometries_utm: list[dict]) -> Grid:
    """20 m grid in EPSG:32630 snapped to multiples of 20 m, which is where every Sentinel-2
    tile of UTM zone 30 puts its 20 m pixel edges, so tiles are read without resampling."""
    xs = [x for g in geometries_utm for polygon in _polygons(g) for ring in polygon for x, *_ in ring]
    ys = [y for g in geometries_utm for polygon in _polygons(g) for ring in polygon for _, y, *_ in ring]
    left = math.floor(min(xs) / RESOLUTION_M) * RESOLUTION_M
    top = math.ceil(max(ys) / RESOLUTION_M) * RESOLUTION_M
    right = math.ceil(max(xs) / RESOLUTION_M) * RESOLUTION_M
    bottom = math.floor(min(ys) / RESOLUTION_M) * RESOLUTION_M
    width = int(round((right - left) / RESOLUTION_M))
    height = int(round((top - bottom) / RESOLUTION_M))
    return Grid(CRS, float(left), float(top), RESOLUTION_M, width, height)


def load_domain(path: Path) -> Domain:
    """Domain polygons (GeoJSON in EPSG:4326), their 20 m grid and the pixel mask inside them."""
    from rasterio.features import rasterize
    from rasterio.warp import transform_geom

    geometries = read_geometries(path)
    projected = [transform_geom("EPSG:4326", CRS, geometry) for geometry in geometries]
    grid = build_grid(projected)
    mask = rasterize(
        [(geometry, 1) for geometry in projected],
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)
    return Domain(geometries, grid, mask)
