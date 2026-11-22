"""render_thumbs: one PNG per catalogue entry for visual review (G-Data).

Each PNG shows the display tiles as the site draws them (from the PMTiles) next to the COG's values, one panel
per band, stretched over the entry's declared value range. Transparent and nodata pixels show as a
checkerboard, so nodata drawn as a value, empty tiles and seams are visible.
"""

from __future__ import annotations

import io
import math
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pipelines.catalog import LocalStorage, Storage

from .objects import byte_reader, local_file

MAX_SIDE = 640
CAPTION_HEIGHT = 16


def _checkerboard(width: int, height: int, cell: int = 8) -> Image.Image:
    y, x = np.indices((height, width))
    grey = np.where(((x // cell) + (y // cell)) % 2 == 0, 200, 150).astype(np.uint8)
    return Image.fromarray(np.dstack([grey, grey, grey, np.full_like(grey, 255)]), "RGBA")


def _over_checkerboard(image: Image.Image) -> Image.Image:
    background = _checkerboard(*image.size)
    background.alpha_composite(image.convert("RGBA"))
    return background.convert("RGB")


def _tile_xy(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Fractional Web Mercator tile coordinates (the XYZ scheme PMTiles uses)."""
    n = 2**zoom
    lat_rad = math.radians(lat)
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * n


def display_image(storage: Storage, key: str, bounds: list[float], max_side: int = MAX_SIDE) -> Image.Image | None:
    """The display tiles over bounds (lon/lat) at the deepest zoom that fits in max_side pixels."""
    from pmtiles.reader import Reader

    reader = byte_reader(storage, key)
    if reader is None:
        return None
    pmtiles = Reader(reader[0])
    header = pmtiles.header()
    west, south, east, north = bounds
    first_tile = None
    zoom = header["min_zoom"]
    for candidate in range(header["min_zoom"], header["max_zoom"] + 1):
        x0, y0 = _tile_xy(west, north, candidate)
        x1, y1 = _tile_xy(east, south, candidate)
        # rio-pmtiles writes 512 px tiles; the size is confirmed from the first tile read below.
        if max(x1 - x0, y1 - y0) * 512 > max_side and candidate > header["min_zoom"]:
            break
        zoom = candidate
    x0, y0 = _tile_xy(west, north, zoom)
    x1, y1 = _tile_xy(east, south, zoom)
    tiles = {}
    for ty in range(int(y0), int(y1) + 1):
        for tx in range(int(x0), int(x1) + 1):
            data = pmtiles.get(zoom, tx, ty)
            if data is not None:
                tiles[(tx, ty)] = Image.open(io.BytesIO(data)).convert("RGBA")
                first_tile = first_tile or tiles[(tx, ty)]
    size = first_tile.width if first_tile is not None else 512
    mosaic = Image.new("RGBA", ((int(x1) - int(x0) + 1) * size, (int(y1) - int(y0) + 1) * size), (0, 0, 0, 0))
    for (tx, ty), tile in tiles.items():
        mosaic.paste(tile, ((tx - int(x0)) * size, (ty - int(y0)) * size))
    box = (
        round((x0 - int(x0)) * size),
        round((y0 - int(y0)) * size),
        max(round((x1 - int(x0)) * size), round((x0 - int(x0)) * size) + 1),
        max(round((y1 - int(y0)) * size), round((y0 - int(y0)) * size) + 1),
    )
    return mosaic.crop(box)


def data_images(
    path: Path, entry: dict[str, Any], max_side: int = MAX_SIDE, window_bounds: list[float] | None = None
) -> list[tuple[str, Image.Image]]:
    """The COG's bands as images: red, green, blue together, any other band alone in grey over its value range."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.open(path) as src:
        window = None
        if window_bounds is not None:
            left, bottom, right, top = transform_bounds("EPSG:4326", src.crs, *window_bounds, densify_pts=21)
            window = from_bounds(left, bottom, right, top, src.transform)
        height, width = (window.height, window.width) if window is not None else (src.height, src.width)
        scale = min(1.0, max_side / max(height, width))
        shape = (src.count, max(1, round(height * scale)), max(1, round(width * scale)))
        data = src.read(
            out_shape=shape, window=window, boundless=window is not None, masked=True, resampling=Resampling.nearest
        )
    bands = entry["bands"]
    panels: list[tuple[str, Image.Image]] = []

    def stretched(index: int) -> np.ndarray:
        low, high = entry["value_range"][index]
        values = np.ma.filled(data[index].astype("float64"), np.nan)
        return np.nan_to_num(np.clip((values - low) / ((high - low) or 1) * 255, 0, 255)).astype(np.uint8)

    if bands[:3] == ["red", "green", "blue"]:
        alpha = np.where(np.ma.getmaskarray(data[:3]).all(axis=0), 0, 255).astype(np.uint8)
        rgba = np.dstack([stretched(0), stretched(1), stretched(2), alpha])
        panels.append(("red,green,blue", Image.fromarray(rgba, "RGBA")))
        others = range(3, len(bands))
    else:
        others = range(len(bands))
    for index in others:
        grey = stretched(index)
        alpha = np.where(np.ma.getmaskarray(data[index]), 0, 255).astype(np.uint8)
        panels.append((bands[index], Image.fromarray(np.dstack([grey, grey, grey, alpha]), "RGBA")))
    return panels


def compose(title: str, panels: list[tuple[str, Image.Image | None]]) -> Image.Image:
    """Panels side by side on a common height, each over a checkerboard with its caption, under a title row."""
    height = max((image.height for _, image in panels if image is not None), default=64)
    scaled: list[tuple[str, Image.Image]] = []
    for caption, image in panels:
        if image is None:
            image = Image.new("RGBA", (height, height), (0, 0, 0, 0))
            caption += " (missing)"
        else:
            image = image.resize((max(1, round(image.width * height / image.height)), height), Image.Resampling.NEAREST)
        scaled.append((caption, _over_checkerboard(image)))
    gap = 6
    width = sum(image.width for _, image in scaled) + gap * (len(scaled) - 1)
    sheet = Image.new("RGB", (max(width, 320), height + 2 * CAPTION_HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((2, 2), title, fill=(0, 0, 0), font=font)
    x = 0
    for caption, image in scaled:
        sheet.paste(image, (x, CAPTION_HEIGHT))
        draw.text((x + 2, CAPTION_HEIGHT + height + 2), caption, fill=(0, 0, 0), font=font)
        x += image.width + gap
    return sheet


def entry_thumbnail(
    storage: Storage, entry: dict[str, Any], folder: Path, bounds: list[float] | None = None, label: str = ""
) -> Image.Image:
    """The review sheet of one entry, over its own bounds or a sub-area (a regression fixture's box)."""
    area = bounds or entry["bounds"]
    display = display_image(storage, entry["pmtiles"], area)
    path = local_file(storage, entry["cog"], folder)
    panels: list[tuple[str, Image.Image | None]] = [("display (PMTiles)", display)]
    if path is None:
        panels.append(("data (COG)", None))
    else:
        try:
            for name, image in data_images(path, entry, window_bounds=bounds):
                low, high = entry["value_range"][entry["bands"].index(name.split(",")[0])]
                panels.append((f"{name} {low:g}..{high:g}", image))
        finally:
            if not isinstance(storage, LocalStorage):
                path.unlink(missing_ok=True)
    title = f"{entry['layer']} {entry['date']} {entry['status']} {entry['resolution_m']} m {label}".strip()
    return compose(title, panels)


def render_thumbs(
    storage: Storage, entries: list[dict[str, Any]], out_dir: Path, workers: int = 4
) -> list[dict[str, str]]:
    """Write out_dir/<layer>/<date>.png for every entry and return what was written."""

    def render(entry: dict[str, Any], tmp: Path) -> dict[str, str]:
        target = out_dir / entry["layer"] / f"{entry['date']}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            entry_thumbnail(storage, entry, tmp).save(target, optimize=True)
        except Exception as error:  # a broken file is check_catalog's finding; the other thumbnails still render
            return {"layer": entry["layer"], "date": entry["date"], "error": f"{type(error).__name__}: {error}"}
        return {"layer": entry["layer"], "date": entry["date"], "png": target.as_posix()}

    with tempfile.TemporaryDirectory(prefix="thumbs-") as tmp, ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda entry: render(entry, Path(tmp)), entries))


def fixture_thumbs(
    storage: Storage, fixtures: list[dict[str, Any]], entries: dict[str, list[dict[str, Any]]], out_dir: Path
) -> list[dict[str, str]]:
    """Write out_dir/fixtures/<id>/<layer>-<date>.png for every published layer and date a fixture scores."""
    written = []
    with tempfile.TemporaryDirectory(prefix="thumbs-") as tmp:
        for fixture in fixtures:
            rule = fixture["rule"]
            wanted = {(rule["observed_layer"], fixture["observation_date"])}
            wanted |= {(rule["model_layer"], date) for date in fixture["model_dates"]}
            for layer, layer_entries in sorted(entries.items()):
                for entry in layer_entries:
                    if (layer, entry["date"]) not in wanted:
                        continue
                    target = out_dir / "fixtures" / fixture["id"] / f"{layer}-{entry['date']}.png"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    row = {"fixture": fixture["id"], "layer": layer, "date": entry["date"]}
                    try:
                        image = entry_thumbnail(storage, entry, Path(tmp), bounds=fixture["bbox"], label=fixture["id"])
                        image.save(target, optimize=True)
                    except Exception as error:  # reported in the thumbnail list; check_catalog names the broken file
                        written.append(row | {"error": f"{type(error).__name__}: {error}"})
                        continue
                    written.append(row | {"png": target.as_posix()})
    return written
