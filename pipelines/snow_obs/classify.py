"""Snow, no snow, cloud and unknown per 20 m pixel from one Sentinel-2 L2A acquisition.

The snow test is the two-pass method of Theia LIS: Gascoin, Grizonnet, Bouchet, Salgues, Hagolle
(2019), "Theia Snow collection: high-resolution operational snow cover maps from Sentinel-2 and
Landsat-8 data", Earth Syst. Sci. Data 11, 493-514, doi:10.5194/essd-11-493-2019, section 3 and
table 2. The parameter values are the LIS defaults of that paper:

- pass 1: NDSI > 0.4 and red > 0.2 on every cloud-free pixel;
- snowline: the DEM in 100 m bands; the lowest band with more than 10% of its pixels cloud-free
  and more than 10% of those snow in pass 1, lowered by two bands; computed only when pass 1 finds
  snow on more than 0.1% of the domain;
- pass 2: NDSI > 0.15 and red > 0.04 on cloud-free pixels at or above the snowline.

LIS takes its cloud mask from MAJA. Here it comes from the Sen2Cor scene classification (SCL),
as in README section 6, with one correction for Sen2Cor calling bright snow cloud (see
`bright_snow`).
"""

from dataclasses import dataclass

import numpy as np

# Class codes of the product's first band. 255 is nodata (outside the domain) in every band.
NO_SNOW = 0
SNOW = 1
CLOUD = 2
UNKNOWN = 3
NODATA = 255

# Confidence band: none for cloud and unknown, low for snow / no snow under forest canopy
# (snow under trees is hidden from the sensor), high otherwise.
CONFIDENCE_NONE = 0
CONFIDENCE_LOW = 1
CONFIDENCE_HIGH = 2

# Flags band (bit mask), so each stratum can be scored apart.
FLAG_FOREST = 1
FLAG_TERRAIN_SHADOW = 2
FLAG_PASS2 = 4
FLAG_BRIGHT_SNOW = 8

NDSI_PASS1 = 0.4
RED_PASS1 = 0.2
NDSI_PASS2 = 0.15
RED_PASS2 = 0.04
SNOWLINE_BAND_M = 100.0
SNOWLINE_MIN_CLEAR_FRACTION = 0.1
SNOWLINE_MIN_SNOW_FRACTION = 0.1
SNOWLINE_LOWER_BANDS = 2
SNOW_TOTAL_MIN_FRACTION = 0.001

# Sen2Cor scene classification (ESA, Sentinel-2 L2A Product Specification): 0 no data,
# 1 saturated or defective, 3 cloud shadow, 8 cloud medium probability, 9 cloud high
# probability, 10 thin cirrus.
SCL_NO_DATA = (0, 1)
SCL_CLOUD = (3, 8, 9, 10)
SCL_CLOUD_MEDIUM = 8
SCL_CLOUD_SURE = (0, 1, 9, 10)


@dataclass(frozen=True)
class Scene:
    """Inputs on the 20 m domain grid. Reflectances are float32 with NaN where no tile has data."""

    green: np.ndarray
    red: np.ndarray
    swir16: np.ndarray
    scl: np.ndarray
    elevation: np.ndarray
    terrain_shadow: np.ndarray
    forest: np.ndarray
    inside: np.ndarray


@dataclass(frozen=True)
class Classification:
    classes: np.ndarray
    confidence: np.ndarray
    flags: np.ndarray
    snowline_m: float | None


def ndsi(green: np.ndarray, swir16: np.ndarray) -> np.ndarray:
    """Normalised difference snow index (green - SWIR) / (green + SWIR); NaN where undefined."""
    total = green + swir16
    with np.errstate(divide="ignore", invalid="ignore"):
        index = (green - swir16) / total
    return np.where(total > 0, index, np.nan).astype("float32")


def snowline(elevation: np.ndarray, snow: np.ndarray, clear: np.ndarray, inside: np.ndarray) -> float | None:
    """Elevation (m) above which pass 2 runs, or None when pass 1 found too little snow."""
    if snow.sum() <= SNOW_TOTAL_MIN_FRACTION * inside.sum():
        return None
    valid = inside & np.isfinite(elevation)
    bands = np.floor(elevation[valid] / SNOWLINE_BAND_M).astype("int64")
    lowest = int(bands.min())
    bands -= lowest
    total = np.bincount(bands)
    clear_count = np.bincount(bands, weights=clear[valid], minlength=total.size)
    snow_count = np.bincount(bands, weights=snow[valid], minlength=total.size)
    for band in range(total.size):
        if total[band] == 0 or clear_count[band] <= SNOWLINE_MIN_CLEAR_FRACTION * total[band]:
            continue
        if snow_count[band] > SNOWLINE_MIN_SNOW_FRACTION * clear_count[band]:
            return float((band + lowest - SNOWLINE_LOWER_BANDS) * SNOWLINE_BAND_M)
    return None


def _grow(mask: np.ndarray) -> np.ndarray:
    """The mask and its 8-connected neighbours."""
    grown = mask.copy()
    grown[1:] |= mask[:-1]
    grown[:-1] |= mask[1:]
    rows = grown.copy()
    grown[:, 1:] |= rows[:, :-1]
    grown[:, :-1] |= rows[:, 1:]
    return grown


def bright_snow(scl: np.ndarray, snow_test: np.ndarray) -> np.ndarray:
    """Pixels Sen2Cor calls medium-probability cloud (SCL 8) that pass the pass-1 snow test and
    lie in an SCL 8 patch that touches no high-probability cloud, cirrus, nodata or grid edge,
    so clear sky surrounds it.

    README section 6 asks to keep as snow the SCL cloud pixels with NDSI > 0.4 and a low cloud
    probability. On the real scenes it was checked on this does not work: Sen2Cor gives the
    round false-cloud patches on a clear snowfield (2026-01-22) and an ice cloud deck (2026-01-27)
    the same probability, 50%, and the same NDSI and SWIR ranges, while the pixels with a low
    probability are the one-pixel rings Sen2Cor adds around every cloud. What does separate them
    is where they are: the false patches sit inside clear snow, real cloud fields join
    high-probability cores. So the correction keeps an SCL 8 patch only when no SCL 0, 1, 9 or 10
    pixel can be reached from it through SCL 8 pixels.
    """
    medium = scl == SCL_CLOUD_MEDIUM
    sure = np.isin(scl, SCL_CLOUD_SURE)
    sure[[0, -1], :] = True
    sure[:, [0, -1]] = True
    reached = _grow(sure) & medium
    frontier = reached
    while frontier.any():
        rows = np.flatnonzero(frontier.any(axis=1))
        cols = np.flatnonzero(frontier.any(axis=0))
        window = (slice(max(rows[0] - 1, 0), rows[-1] + 2), slice(max(cols[0] - 1, 0), cols[-1] + 2))
        grown = _grow(frontier[window]) & medium[window] & ~reached[window]
        frontier = np.zeros_like(frontier)
        frontier[window] = grown
        reached[window] |= grown
    return medium & ~reached & snow_test


def classify(scene: Scene) -> Classification:
    inside = scene.inside
    has_data = (
        inside
        & np.isfinite(scene.green)
        & np.isfinite(scene.red)
        & np.isfinite(scene.swir16)
        & ~np.isin(scene.scl, SCL_NO_DATA)
    )
    index = ndsi(scene.green, scene.swir16)
    with np.errstate(invalid="ignore"):
        pass1 = has_data & (index > NDSI_PASS1) & (scene.red > RED_PASS1)
        loose = has_data & (index > NDSI_PASS2) & (scene.red > RED_PASS2)

    kept = bright_snow(scene.scl, pass1)
    cloud = has_data & np.isin(scene.scl, SCL_CLOUD) & ~kept
    clear = has_data & ~cloud
    snow1 = pass1 & clear

    line = snowline(scene.elevation, snow1, clear, inside)
    if line is None:
        snow2 = np.zeros_like(snow1)
    else:
        with np.errstate(invalid="ignore"):
            snow2 = loose & clear & ~snow1 & (scene.elevation >= line)
    snow = snow1 | snow2
    # A dark pixel in terrain shadow is no evidence of bare ground (README section 6).
    unknown = (inside & ~has_data) | (clear & ~snow & scene.terrain_shadow)
    no_snow = clear & ~snow & ~scene.terrain_shadow

    classes = np.full(inside.shape, NODATA, dtype="uint8")
    classes[no_snow] = NO_SNOW
    classes[snow] = SNOW
    classes[cloud] = CLOUD
    classes[unknown] = UNKNOWN

    confidence = np.full(inside.shape, NODATA, dtype="uint8")
    confidence[inside] = CONFIDENCE_NONE
    observed = snow | no_snow
    confidence[observed] = CONFIDENCE_HIGH
    confidence[observed & scene.forest] = CONFIDENCE_LOW

    flags = np.zeros(inside.shape, dtype="uint8")
    flags[scene.forest] |= FLAG_FOREST
    flags[scene.terrain_shadow] |= FLAG_TERRAIN_SHADOW
    flags[snow2] |= FLAG_PASS2
    flags[kept & snow] |= FLAG_BRIGHT_SNOW
    flags[~inside] = NODATA
    return Classification(classes, confidence, flags, line)
