"""Colour the display rasters with the map ramps the site's legends read.

docs/design/ramps.json (built by docs/design/tools/build_ramps.py) is the single source of the snow layer
colours: every pipeline that renders a display image for publish() colours it here, and the frontend legend
draws the same classes from the same file, so a legend cannot disagree with the image.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

RAMPS_JSON = Path(__file__).resolve().parents[1] / "docs" / "design" / "ramps.json"

# The ramp each catalogue layer (pipelines/catalog/layers.py) is drawn with. True colour has none: it is an
# image, not a value. frontend/src/lib/layers.ts holds the same pairs; tests/test_ramps.py keeps them equal.
RAMP_OF_LAYER = {
    "snow_obs": "snow_cover_observed",
    "snow_gapfill": "snow_cover_probability",
    "swe": "swe",
    "snow_depth": "snow_depth",
}


@lru_cache(maxsize=1)
def ramps() -> dict[str, Any]:
    layers: dict[str, Any] = json.loads(RAMPS_JSON.read_text(encoding="utf-8"))["layers"]
    return layers


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    value = int(hex_colour.lstrip("#"), 16)
    return value >> 16, (value >> 8) & 255, value & 255


def _paint(rgba: np.ndarray, where: np.ndarray, colour: str, alpha: float) -> None:
    rgba[where, :3] = _rgb(colour)
    rgba[where, 3] = round(alpha * 255)


def _pattern_mask(shape: tuple[int, int], pattern: dict[str, Any]) -> np.ndarray:
    """Pixels of a dot or 45 degree hatch pattern, anchored to the raster grid so tiles join without seams."""
    rows, cols = np.indices(shape)
    spacing = int(pattern["spacing_px"])
    if pattern["kind"] == "dots":
        radius = int(pattern["radius_px"])
        dy = (rows % spacing) - spacing // 2
        dx = (cols % spacing) - spacing // 2
        return np.asarray(dx * dx + dy * dy <= radius * radius)
    if pattern["kind"] == "hatch":
        return np.asarray((rows + cols) % spacing < int(pattern["width_px"]))
    raise ValueError(f"Unknown pattern kind {pattern['kind']!r}")


def colour_values(values: np.ndarray, ramp_id: str) -> np.ndarray:
    """RGBA uint8 image of a continuous layer (SWE, depth, probability) in the stepped classes of its ramp.

    Classes are min inclusive, max exclusive (open when max is null). NaN and values below the first class
    are transparent, as are classes the ramp leaves without a colour.
    """
    ramp = ramps()[ramp_id]
    if ramp.get("categorical"):
        raise ValueError(f"{ramp_id} is categorical; use colour_classes")
    data = np.asarray(values, dtype="float64")
    rgba = np.zeros((*data.shape, 4), dtype="uint8")
    finite = np.isfinite(data)
    for cls in ramp["classes"]:
        if cls["color"] is None:
            continue
        inside = finite & (data >= cls["min"])
        if cls["max"] is not None:
            inside &= data < cls["max"]
        _paint(rgba, inside, cls["color"], cls["alpha"])
    return rgba


def colour_classes(keys: np.ndarray, ramp_id: str) -> np.ndarray:
    """RGBA uint8 image of a class layer from an array of class keys ("snow", "cloud", ...) of the ramp.

    Each class gets its fill colour and alpha, then its pattern (dots or hatch) on top. An empty key ("")
    is transparent; any other key the ramp does not define is an error, so a classifier code can never
    be drawn in a colour the legend does not show.
    """
    ramp = ramps()[ramp_id]
    if not ramp.get("categorical"):
        raise ValueError(f"{ramp_id} is continuous; use colour_values")
    keys = np.asarray(keys)
    known = {cls["key"] for cls in ramp["classes"]}
    unknown = set(np.unique(keys).tolist()) - known - {""}
    if unknown:
        raise ValueError(f"Class keys not in ramp {ramp_id}: {sorted(unknown)}")
    rgba = np.zeros((*keys.shape, 4), dtype="uint8")
    for cls in ramp["classes"]:
        inside = keys == cls["key"]
        if cls["color"] is not None:
            _paint(rgba, inside, cls["color"], cls["alpha"])
        pattern = cls.get("pattern")
        if pattern:
            _paint(rgba, inside & _pattern_mask(keys.shape, pattern), pattern["color"], pattern.get("alpha", 1.0))
    return rgba
