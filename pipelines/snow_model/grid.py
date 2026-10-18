import hashlib
from dataclasses import dataclass

import numpy as np

OBSERVATION_RESOLUTION_M = 10.0


def utm_crs(lon: float, lat: float) -> str:
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


@dataclass(frozen=True)
class Grid:
    crs: str
    left: float
    top: float
    resolution: float
    width: int
    height: int

    @property
    def transform(self):
        from rasterio.transform import from_origin

        return from_origin(self.left, self.top, self.resolution, self.resolution)

    @property
    def cell_area_m2(self) -> float:
        return self.resolution * self.resolution

    @property
    def factor(self) -> int:
        return int(round(self.resolution / OBSERVATION_RESOLUTION_M))

    def refined(self) -> "Grid":
        """The same extent at the Sentinel-2 resolution."""
        factor = self.factor
        return Grid(
            self.crs,
            self.left,
            self.top,
            OBSERVATION_RESOLUTION_M,
            self.width * factor,
            self.height * factor,
        )

    def signature(self) -> str:
        text = f"{self.crs}|{self.left}|{self.top}|{self.resolution}|{self.width}|{self.height}"
        return hashlib.sha1(text.encode()).hexdigest()[:12]

    def lonlat_corners(self) -> list[list[float]]:
        """Top-left, top-right, bottom-right and bottom-left corners in longitude and latitude."""
        from rasterio.warp import transform

        right = self.left + self.width * self.resolution
        bottom = self.top - self.height * self.resolution
        xs = [self.left, right, right, self.left]
        ys = [self.top, self.top, bottom, bottom]
        lons, lats = transform(self.crs, "EPSG:4326", xs, ys)
        return [[lon, lat] for lon, lat in zip(lons, lats)]

    def cell_centres_lonlat(self):
        from rasterio.warp import transform

        columns = self.left + (np.arange(self.width) + 0.5) * self.resolution
        rows = self.top - (np.arange(self.height) + 0.5) * self.resolution
        xs, ys = np.meshgrid(columns, rows)
        lons, lats = transform(self.crs, "EPSG:4326", xs.ravel(), ys.ravel())
        shape = (self.height, self.width)
        return np.asarray(lons).reshape(shape), np.asarray(lats).reshape(shape)


def build_grid(bbox: tuple[float, float, float, float], resolution: float) -> Grid:
    """A UTM grid covering the box, snapped so Sentinel-2 pixels nest exactly in each cell."""
    from rasterio.warp import transform_bounds

    if resolution % 20:
        raise ValueError("Grid resolution must be a multiple of 20 m")
    west, south, east, north = bbox
    crs = utm_crs((west + east) / 2, (south + north) / 2)
    left, bottom, right, top = transform_bounds("EPSG:4326", crs, west, south, east, north)
    left = np.floor(left / resolution) * resolution
    top = np.ceil(top / resolution) * resolution
    width = int(np.ceil((right - left) / resolution))
    height = int(np.ceil((top - bottom) / resolution))
    return Grid(crs, float(left), float(top), float(resolution), width, height)
