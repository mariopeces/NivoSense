"""Chip pages for labelling and reviewing the reference sample.

Every point is shown as three panels cut from the 10 m L1C mosaic of its date:
true colour (B04/B03/B02) and SWIR false colour (B11/B8/B4) zoomed on the 340 m around the
point, and a 1 km true-colour context panel. The labelled 20 m pixel sits inside the red
corner marks. Both stretches are fixed and the same for every date: reflectance 0 to 1 with
a square-root curve, so bright snow is not saturated and shadowed slopes stay readable.

    python -m qa.reference.chips pages --points P.geojson --cache C --out DIR        labelling pages, no labels
    python -m qa.reference.chips strata --points qa/reference/snow_points.geojson --cache C --out DIR
    python -m qa.reference.chips blind --points qa/reference/snow_points.geojson --cache C --out DIR
    python -m qa.reference.chips agreement --points qa/reference/snow_points.geojson --labels relabel.csv
"""

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from pipelines.s2.domain import convex_hull, load_domain

from . import layers
from .sample import domain_part

LABELS = ("snow", "no_snow", "cloud", "unsure")
ZOOM_PX = 34
CONTEXT_PX = 102
SCALE = 3
GAP = 4
CAPTION = 14
COLUMNS = 4
ROWS = 8
STRETCH_MAX = 1.0
MARK = (255, 0, 0)
BLIND_SEED = 1010
BLIND_FRACTION = 0.10


def stretch(reflectance: np.ndarray) -> np.ndarray:
    """Fixed square-root stretch of reflectance 0..STRETCH_MAX to 0..255; NaN to black."""
    values = np.clip(np.nan_to_num(reflectance, nan=0.0) / STRETCH_MAX, 0.0, 1.0)
    return np.round(np.sqrt(values) * 255).astype("uint8")


def window(mosaic: layers.L1CMosaic, row: int, col: int, size: int, bands: tuple[str, str, str]) -> np.ndarray:
    """size x size 10 m pixels whose centre 2x2 block starts at (row, col); NaN off the mosaic."""
    half = size // 2 - 1
    height, width = mosaic.source.shape
    out = np.full((size, size, 3), np.nan, dtype="float32")
    r0, c0 = row - half, col - half
    rs, cs = max(r0, 0), max(c0, 0)
    re, ce = min(r0 + size, height), min(c0 + size, width)
    for index, band in enumerate(bands):
        out[rs - r0 : re - r0, cs - c0 : ce - c0, index] = mosaic.reflectance[band][rs:re, cs:ce]
    return out


def marked(image: np.ndarray, size: int, scale: int) -> np.ndarray:
    """Upscale by `scale` and draw red corner marks just outside the centre 2x2 block."""
    big = image.repeat(scale, axis=0).repeat(scale, axis=1)
    half = size // 2 - 1
    lo, hi = half * scale - 2, (half + 2) * scale + 1
    tick = max(3, scale + 1)
    for r, c, dr, dc in ((lo, lo, 1, 1), (lo, hi, 1, -1), (hi, lo, -1, 1), (hi, hi, -1, -1)):
        for step in range(tick):
            for rr, cc in ((r + dr * step, c), (r, c + dc * step)):
                if 0 <= rr < big.shape[0] and 0 <= cc < big.shape[1]:
                    big[rr, cc] = MARK
    return big


def point_panels(mosaic: layers.L1CMosaic, row: int, col: int) -> list[np.ndarray]:
    true_colour = ("red", "green", "blue")
    swir = ("swir16", "nir", "red")
    context_scale = ZOOM_PX * SCALE // CONTEXT_PX
    return [
        marked(stretch(window(mosaic, row, col, ZOOM_PX, true_colour)), ZOOM_PX, SCALE),
        marked(stretch(window(mosaic, row, col, ZOOM_PX, swir)), ZOOM_PX, SCALE),
        marked(stretch(window(mosaic, row, col, CONTEXT_PX, true_colour)), CONTEXT_PX, context_scale),
    ]


def mosaic_cell(x: float, y: float, grid: layers.Grid) -> tuple[int, int]:
    """Row and column of the top-left 10 m cell of the 20 m pixel centred at (x, y)."""
    col = int(round((x - grid.left) / grid.resolution - 1))
    row = int(round((grid.top - y) / grid.resolution - 1))
    return row, col


def page(points: list[dict], panels: dict[str, list[np.ndarray]], captions: dict[str, str]):  # noqa: ANN201
    from PIL import Image, ImageDraw, ImageFont

    panel = ZOOM_PX * SCALE
    cell_w, cell_h = 3 * panel + 2 * GAP, panel + CAPTION
    columns = min(COLUMNS, len(points))
    rows = -(-len(points) // columns)
    canvas = Image.new("RGB", (columns * (cell_w + 3 * GAP), rows * (cell_h + GAP)), (40, 40, 40))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=12)
    for index, point in enumerate(points):
        point_id = point["properties"]["id"]
        left = (index % columns) * (cell_w + 3 * GAP)
        top = (index // columns) * (cell_h + GAP)
        for number, array in enumerate(panels[point_id]):
            canvas.paste(Image.fromarray(array), (left + number * (panel + GAP), top + CAPTION))
        draw.text((left, top), captions.get(point_id, point_id), fill=(255, 255, 255), font=font)
    return canvas


def load_points(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render_panels(points: list[dict], collection: dict, domain_path: Path, cache: Path) -> dict[str, list[np.ndarray]]:
    """Panels of every point, loading one date's 10 m mosaic at a time (each is about 0.7 GB)."""
    domain = load_domain(domain_part(domain_path, cache))
    grid = layers.resampled(domain.grid, 10.0)
    hull = convex_hull(domain.geometries)
    orbits = {meta["date"]: meta["orbit"] for meta in collection["metadata"]["dates"]}
    by_date: dict[str, list[dict]] = defaultdict(list)
    for point in points:
        by_date[point["properties"]["date"]].append(point)
    panels = {}
    for day in sorted(by_date):
        mosaic = layers.cached_l1c(cache, date.fromisoformat(day), orbits[day], hull, grid)
        for point in by_date[day]:
            row, col = mosaic_cell(point["properties"]["x"], point["properties"]["y"], grid)
            panels[point["properties"]["id"]] = point_panels(mosaic, row, col)
        del mosaic
    return panels


def write_pages(points: list[dict], panels: dict[str, list[np.ndarray]], out: Path, prefix: str) -> list[Path]:
    """Pages of ROWS x COLUMNS points in the given order, each page holding one date."""
    out.mkdir(parents=True, exist_ok=True)
    by_date: dict[str, list[dict]] = defaultdict(list)
    for point in points:
        by_date[point["properties"]["date"]].append(point)
    paths = []
    per_page = ROWS * COLUMNS
    for day in sorted(by_date):
        chunk = by_date[day]
        for start in range(0, len(chunk), per_page):
            path = out / f"{prefix}_{day}_{start // per_page:02d}.png"
            page(chunk[start : start + per_page], panels, {}).save(path)
            paths.append(path)
    return paths


def labelling_order(points: list[dict], seed: int) -> list[dict]:
    """Points of each date shuffled, so a page mixes strata and the drawing order is hidden."""
    shuffled = list(points)
    random.Random(seed).shuffle(shuffled)
    return sorted(shuffled, key=lambda point: point["properties"]["date"])


def blind_subset(points: list[dict], fraction: float = BLIND_FRACTION, seed: int = BLIND_SEED) -> list[dict]:
    """A simple random `fraction` of the points, at least one."""
    count = max(1, round(len(points) * fraction))
    return random.Random(seed).sample(points, count)


def read_labels(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        labels = {row["id"]: row["label"].strip() for row in csv.DictReader(handle)}
    unknown = sorted({label for label in labels.values() if label not in LABELS})
    if unknown:
        raise ValueError(f"Unknown labels in {path}: {unknown}")
    return labels


def agreement(points: list[dict], relabels: dict[str, str]) -> dict:
    """Agreement of a relabel with the frozen labels, excluding points either side marked
    unsure, plus the full cross-table and the agreement per stratum."""
    frozen = {point["properties"]["id"]: point["properties"] for point in points}
    missing = sorted(set(relabels) - set(frozen))
    if missing:
        raise ValueError(f"Relabelled ids not in the sample: {missing[:5]}")
    table: Counter = Counter()
    per_stratum: dict[str, Counter] = defaultdict(Counter)
    for point_id, relabel in relabels.items():
        label = frozen[point_id]["label"]
        table[(label, relabel)] += 1
        if "unsure" in (label, relabel):
            continue
        per_stratum[frozen[point_id]["stratum"]]["compared"] += 1
        per_stratum[frozen[point_id]["stratum"]]["agree"] += int(label == relabel)
    compared = sum(counts["compared"] for counts in per_stratum.values())
    agreed = sum(counts["agree"] for counts in per_stratum.values())
    return {
        "relabelled": len(relabels),
        "compared": compared,
        "agreed": agreed,
        "agreement": round(agreed / compared, 4) if compared else None,
        "cross_table": {f"{label}->{relabel}": count for (label, relabel), count in sorted(table.items())},
        "per_stratum": {
            name: {**counts, "agreement": round(counts["agree"] / counts["compared"], 4)}
            for name, counts in sorted(per_stratum.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("pages", "strata", "blind", "agreement"))
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--domain", type=Path, default=Path("data/domain.geojson"))
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--labels", type=Path, help="agreement: CSV with columns id,label")
    parser.add_argument("--per-stratum", type=int, default=32, help="strata: points shown per stratum")
    parser.add_argument("--seed", type=int, default=BLIND_SEED)
    parser.add_argument("--fraction", type=float, default=BLIND_FRACTION)
    args = parser.parse_args(argv)
    collection = load_points(args.points)
    points = collection["features"]

    if args.command == "agreement":
        if args.labels is None:
            parser.error("agreement needs --labels")
        print(json.dumps(agreement(points, read_labels(args.labels)), indent=2))
        return 0
    if args.cache is None or args.out is None:
        parser.error(f"{args.command} needs --cache and --out")

    if args.command == "pages":
        ordered = labelling_order(points, args.seed)
        paths = write_pages(ordered, render_panels(ordered, collection, args.domain, args.cache), args.out, "page")
    elif args.command == "blind":
        subset = blind_subset(points, args.fraction, args.seed)
        args.out.mkdir(parents=True, exist_ok=True)
        with (args.out / "blind_labels.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "label"])
            for point in sorted(subset, key=lambda p: p["properties"]["id"]):
                writer.writerow([point["properties"]["id"], ""])
        ordered = labelling_order(subset, args.seed)
        paths = write_pages(ordered, render_panels(ordered, collection, args.domain, args.cache), args.out, "blind")
    else:
        shown = {}
        for stratum in sorted({point["properties"]["stratum"] for point in points}):
            members = [point for point in points if point["properties"]["stratum"] == stratum]
            picked = random.Random(args.seed).sample(members, min(args.per_stratum, len(members)))
            shown[stratum] = sorted(picked, key=lambda p: (p["properties"]["label"], p["properties"]["date"]))
        panels = render_panels([p for group in shown.values() for p in group], collection, args.domain, args.cache)
        args.out.mkdir(parents=True, exist_ok=True)
        paths = []
        for stratum, group in shown.items():
            captions = {p["properties"]["id"]: f"{p['properties']['id']} {p['properties']['label']}" for p in group}
            path = args.out / f"stratum_{stratum}.png"
            page(group, panels, captions).save(path)
            paths.append(path)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
