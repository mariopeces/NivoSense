"""Draw the stratified points of the reference sample (no labels).

    python -m qa.reference.sample --cache work/reference --out work/reference/points.geojson

For every date in qa/reference/dates.json it reads the L2A scene classes (cloud only, for the
cloud-edge stratum) and sun angles, builds the 10 m L1C mosaic the chips are cut from, and
draws points per stratum and elevation band. Rerunning with the same inputs and seed draws
the same points.

    python -m qa.reference.sample --cache C --out points2.geojson --supplement points.geojson --draw 2
    python -m qa.reference.sample --cache C --out points3.geojson --supplement points2.geojson --draw 3
    python -m qa.reference.sample --cache C --out points4.geojson --supplement points3.geojson --draw 4

draw the later, snow-prone samples (`SUPPLEMENTS`) on top of the earlier ones, and write all
draws together with the pixel and point counts of every draw cell (metadata.cells).
"""

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from pipelines.s2.domain import Domain, Grid, convex_hull, load_domain
from pipelines.s2.stac import group_acquisitions, search_items, tile_of

from . import layers, strata

DATES_PATH = Path(__file__).with_name("dates.json")
SEED = 20261122
POINTS_PER_STRATUM = 360
# Shadows are traced from terrain up to this far outside the domain.
PAD_M = strata.SHADOW_MAX_DISTANCE_M


@dataclass(frozen=True)
class Supplement:
    """A later draw on the dates that have a snowline, from the same strata and elevation
    bands restricted to ground at least `above_snowline_m` above the date's snowline_m."""

    seed: int
    above_snowline_m: float
    quotas: dict[str, int]


# The first draw left snow thin where snow is rare (20 snow points in forest, 24 at cloud
# edges, almost all of them above the date's snowline). Snow can be targeted without looking
# at the images only through the DEM and the snowline read on the overviews: draw 2 samples
# ground above the snowline; in draws 1 and 2 about half the forest and cloud-edge points
# more than 500 m above it were snow, against under a tenth near it, so draw 3 samples there
# to bring both strata to 100 scored snow points.
SUPPLEMENTS = {
    2: Supplement(
        20261123,
        0.0,
        {"snowline_band": 40, "terrain_shadow": 40, "forest": 120, "cloud_edge": 100, "open_terrain": 40},
    ),
    3: Supplement(20261124, 500.0, {"forest": 200, "cloud_edge": 200}),
    # Draw 3 ran out of cloud-edge ground 500 m above the snowline (137 of 200 points at the
    # minimum spacing) and left cloud edge 3 snow points short of 100.
    4: Supplement(20261125, 200.0, {"cloud_edge": 80}),
}


@dataclass(frozen=True)
class DateSpec:
    day: date
    orbit: str
    phase: str
    snowline_m: float | None


def read_dates(path: Path = DATES_PATH) -> list[DateSpec]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        DateSpec(date.fromisoformat(entry["date"]), entry["orbit"], entry["phase"], entry["snowline_m"])
        for entry in payload["dates"]
    ]


def domain_part(path: Path, cache: Path) -> Path:
    """GeoJSON holding only the `domain` feature of data/domain.geojson (the union of the two
    parks); a file without `part` properties is used as it is."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = [f for f in payload.get("features", []) if f.get("properties", {}).get("part") == "domain"]
    if not features:
        return path
    out = cache / "domain_part.geojson"
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    return out


def static_layers(domain: Domain, cache: Path) -> tuple[np.ndarray, np.ndarray]:
    """Elevation on the padded 20 m grid and tree fraction on the domain grid, cached."""
    elevation_path, trees_path = cache / "elevation_padded.npy", cache / "tree_fraction.npy"
    if not elevation_path.exists():
        np.save(elevation_path, layers.read_elevation(layers.padded(domain.grid, PAD_M)))
    if not trees_path.exists():
        np.save(trees_path, layers.read_tree_fraction(domain.grid))
    return np.load(elevation_path), np.load(trees_path)


def l2a_items(spec: DateSpec, domain: Domain) -> list[dict]:
    items = search_items(convex_hull(domain.geometries), spec.day, spec.day)
    items = [item for item in items if domain.touches(item["geometry"])]
    # The sample was drawn on every datatake of the pass together (2026-02-16 R094 has an S2A
    # and an S2B datatake); keep them together so a rerun draws the frozen points again.
    pass_items = [
        item
        for acquisition in group_acquisitions(items)
        if acquisition.day == spec.day and acquisition.orbit == spec.orbit
        for item in acquisition.items
    ]
    if not pass_items:
        raise ValueError(f"No L2A acquisition on {spec.day} orbit {spec.orbit}")
    latest_first = sorted(pass_items, key=lambda item: item["properties"]["s2:generation_time"], reverse=True)
    return sorted(latest_first, key=tile_of)


def sun_angles(items: list[dict]) -> tuple[float, float]:
    """Mean sun azimuth and elevation of the tiles (they differ by under 1.5 degrees)."""
    azimuth = float(np.mean([item["properties"]["view:sun_azimuth"] for item in items]))
    elevation = float(np.mean([item["properties"]["view:sun_elevation"] for item in items]))
    return azimuth, elevation


def single_tile(source: np.ndarray) -> np.ndarray:
    """20 m pixels whose four 10 m cells all come from one L1C tile."""
    height, width = source.shape[0] // 2, source.shape[1] // 2
    blocks = source.reshape(height, 2, width, 2)
    first = blocks[:, 0, :, 0]
    same = (blocks == first[:, None, :, None]).all(axis=(1, 3))
    return same & (first >= 0)


def crop(padded_array: np.ndarray, domain: Grid, padded_grid: Grid) -> np.ndarray:
    row = int(round((padded_grid.top - domain.top) / domain.resolution))
    col = int(round((domain.left - padded_grid.left) / domain.resolution))
    return padded_array[row : row + domain.height, col : col + domain.width]


def date_layers(spec: DateSpec, domain_path: Path, cache: Path) -> dict:
    """Per-date strata inputs, written to the cache; returns the date's metadata."""
    domain = load_domain(domain_path)
    elevation_padded, trees = static_layers(domain, cache)
    padded_grid = layers.padded(domain.grid, PAD_M)
    items = l2a_items(spec, domain)
    azimuth, sun_elevation = sun_angles(items)
    scl = layers.read_scl(items, domain.grid)
    grid10 = layers.resampled(domain.grid, 10.0)
    l1c = layers.cached_l1c(cache, spec.day, spec.orbit, convex_hull(domain.geometries), grid10)
    cos_i = crop(
        strata.cos_incidence(elevation_padded, padded_grid.resolution, azimuth, sun_elevation), domain.grid, padded_grid
    )
    shadow = crop(
        strata.cast_shadow(elevation_padded, padded_grid.resolution, azimuth, sun_elevation), domain.grid, padded_grid
    )
    elevation = crop(elevation_padded, domain.grid, padded_grid)
    eligible = domain.mask & single_tile(l1c.source) & np.isfinite(elevation) & np.isfinite(cos_i)
    eligible &= scl != layers.SCL_NODATA
    np.savez_compressed(
        cache / f"layers_{spec.day.isoformat()}.npz",
        cos_incidence=cos_i.astype("float32"),
        cast_shadow=shadow,
        cloud=np.isin(scl, layers.SCL_CLOUD),
        clear=~np.isin(scl, layers.SCL_CLOUD) & (scl != layers.SCL_NODATA),
        eligible=eligible,
        source=l1c.source.reshape(domain.grid.height, 2, domain.grid.width, 2)[:, 0, :, 0],
    )
    return {
        "date": spec.day.isoformat(),
        "orbit": spec.orbit,
        "phase": spec.phase,
        "snowline_m": spec.snowline_m,
        "sun_azimuth": round(azimuth, 3),
        "sun_elevation": round(sun_elevation, 3),
        "l2a_scene_ids": [item["id"] for item in items],
        "l1c_scene_ids": list(l1c.item_ids),
    }


def load_layers(cache: Path, day: date, elevation: np.ndarray, trees: np.ndarray) -> tuple[strata.Layers, np.ndarray]:
    stored = np.load(cache / f"layers_{day.isoformat()}.npz")
    return (
        strata.Layers(
            elevation=elevation,
            cos_incidence=stored["cos_incidence"],
            cast_shadow=stored["cast_shadow"],
            tree_fraction=trees,
            cloud=stored["cloud"],
            clear=stored["clear"],
            eligible=stored["eligible"],
        ),
        stored["source"],
    )


def date_masks(day_layers: strata.Layers, snowline_m: float | None) -> dict[str, np.ndarray]:
    """Stratum masks; outside the cloud-edge stratum only SCL clear-sky pixels are drawn, so
    labelling time goes to points that can show snow or bare ground."""
    masks = strata.stratum_masks(day_layers, snowline_m)
    return {name: mask if name == "cloud_edge" else mask & day_layers.clear for name, mask in masks.items()}


def date_quotas(counts: dict[str, list[int]], per_stratum: int) -> dict[str, list[int]]:
    """Points per stratum split evenly over the dates where the stratum has pixels."""
    return {name: strata.split_quota(per_stratum, sizes) for name, sizes in counts.items()}


def run(domain_path: Path, cache: Path, out: Path, workers: int, per_stratum: int = POINTS_PER_STRATUM) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    domain_path = domain_part(domain_path, cache)
    specs = read_dates()
    domain = load_domain(domain_path)
    elevation_padded, trees = static_layers(domain, cache)
    elevation = crop(elevation_padded, domain.grid, layers.padded(domain.grid, PAD_M))
    with ProcessPoolExecutor(workers) as pool:
        metadata = list(pool.map(date_layers, specs, [domain_path] * len(specs), [cache] * len(specs)))

    bands = strata.elevation_band(elevation)
    masks = []
    for spec in specs:
        day_layers, _ = load_layers(cache, spec.day, elevation, trees)
        masks.append(date_masks(day_layers, spec.snowline_m))
    counts = {name: [int(m[name].sum()) for m in masks] for name in strata.STRATA}
    quotas = date_quotas(counts, per_stratum)

    features: list[dict] = []
    for index, (spec, meta, date_mask) in enumerate(zip(specs, metadata, masks)):
        day_layers, source = load_layers(cache, spec.day, elevation, trees)
        rng = np.random.default_rng([SEED, index])
        draws = strata.draw_points(
            date_mask, bands, {name: quotas[name][index] for name in strata.STRATA}, rng, domain.grid.resolution
        )
        features.extend(
            point_feature(draw, number, 1, spec, meta, day_layers, source, domain.grid, date_mask)
            for number, draw in enumerate(draws)
        )
    collection = {
        "type": "FeatureCollection",
        "metadata": {"seed": SEED, "points_per_stratum": per_stratum, "dates": metadata, "stratum_pixels": counts},
        "features": features,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(collection, indent=1) + "\n", encoding="utf-8")
    return collection


def grid_cell(x: float, y: float, grid: Grid) -> tuple[int, int]:
    return int((grid.top - y) // grid.resolution), int((x - grid.left) // grid.resolution)


def supplement_masks(
    full: dict[str, np.ndarray], elevation: np.ndarray, snowline_m: float, plan: Supplement
) -> dict[str, np.ndarray]:
    above = elevation >= snowline_m + plan.above_snowline_m
    return {name: mask & above for name, mask in full.items()}


def supplement(base: dict, number: int, domain_path: Path, cache: Path, out: Path) -> dict:
    """Draw `number` of `SUPPLEMENTS` on top of the points in `base`, keeping the minimum
    spacing to every earlier point of the same date; writes all draws together."""
    plan = SUPPLEMENTS[number]
    domain_path = domain_part(domain_path, cache)
    domain = load_domain(domain_path)
    elevation_padded, trees = static_layers(domain, cache)
    elevation = crop(elevation_padded, domain.grid, layers.padded(domain.grid, PAD_M))
    bands = strata.elevation_band(elevation)
    metadata = {meta["date"]: meta for meta in base["metadata"]["dates"]}
    specs = [spec for spec in read_dates() if spec.snowline_m is not None]
    full_masks, masks = [], []
    for spec in specs:
        day_layers, _ = load_layers(cache, spec.day, elevation, trees)
        full = date_masks(day_layers, spec.snowline_m)
        full_masks.append(full)
        masks.append(supplement_masks(full, elevation, spec.snowline_m or 0.0, plan))
    counts = {name: [int(m[name].sum()) for m in masks] for name in strata.STRATA}
    quotas = {name: strata.split_quota(plan.quotas.get(name, 0), counts[name]) for name in strata.STRATA}

    features = [{**f, "properties": {"draw": 1, **f["properties"]}} for f in base["features"]]
    for index, (spec, date_mask, full) in enumerate(zip(specs, masks, full_masks)):
        day = spec.day.isoformat()
        earlier = [f["properties"] for f in base["features"] if f["properties"]["date"] == day]
        day_layers, source = load_layers(cache, spec.day, elevation, trees)
        rng = np.random.default_rng([plan.seed, index])
        draws = strata.draw_points(
            date_mask,
            bands,
            {name: quotas[name][index] for name in strata.STRATA},
            rng,
            domain.grid.resolution,
            taken=[grid_cell(p["x"], p["y"], domain.grid) for p in earlier],
        )
        features.extend(
            point_feature(draw, len(earlier) + n, number, spec, metadata[day], day_layers, source, domain.grid, full)
            for n, draw in enumerate(draws)
        )
    supplements = {key: value for key, value in base["metadata"].get("supplements", {}).items()}
    supplements[str(number)] = {
        "seed": plan.seed,
        "above_snowline_m": plan.above_snowline_m,
        "quotas": plan.quotas,
        "dates": [spec.day.isoformat() for spec in specs],
        "restriction": f"elevation at least {plan.above_snowline_m:.0f} m above the date's snowline_m",
    }
    collection: dict = {
        "type": "FeatureCollection",
        "metadata": {**base["metadata"], "supplements": supplements},
        "features": features,
    }
    collection["metadata"].pop("supplement", None)
    collection["metadata"]["cells"] = cell_table(collection, domain, elevation, trees, bands, cache)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(collection, indent=1) + "\n", encoding="utf-8")
    return collection


def cell_table(
    collection: dict, domain: Domain, elevation: np.ndarray, trees: np.ndarray, bands: np.ndarray, cache: Path
) -> list[dict]:
    """Pixels and points drawn per (draw, date, stratum, elevation band) cell: the inclusion
    probability of a pixel in a cell is points / pixels."""
    drawn: dict[tuple[int, str, str, str], int] = {}
    for feature in collection["features"]:
        p = feature["properties"]
        key = (p["draw"], p["date"], p["stratum"], p["elevation_band"])
        drawn[key] = drawn.get(key, 0) + 1
    numbers = sorted({p["properties"]["draw"] for p in collection["features"]})
    rows = []
    for spec in read_dates():
        day_layers, _ = load_layers(cache, spec.day, elevation, trees)
        full = date_masks(day_layers, spec.snowline_m)
        for number in numbers:
            if number == 1:
                masks = full
            elif spec.snowline_m is None:
                continue
            else:
                masks = supplement_masks(full, elevation, float(spec.snowline_m), SUPPLEMENTS[number])
            for name in strata.STRATA:
                for band in range(len(strata.ELEVATION_BREAKS_M) + 1):
                    pixels = int((masks[name] & (bands == band)).sum())
                    band_name = strata.band_name(band)
                    points = drawn.get((number, spec.day.isoformat(), name, band_name), 0)
                    if pixels or points:
                        rows.append(
                            {
                                "draw": number,
                                "date": spec.day.isoformat(),
                                "stratum": name,
                                "elevation_band": band_name,
                                "pixels": pixels,
                                "points": points,
                            }
                        )
    return rows


def point_feature(
    draw: strata.Draw,
    number: int,
    draw_number: int,
    spec: DateSpec,
    meta: dict,
    day_layers: strata.Layers,
    source: np.ndarray,
    grid: Grid,
    date_mask: dict[str, np.ndarray],
) -> dict:
    from rasterio.warp import transform

    x = grid.left + (draw.col + 0.5) * grid.resolution
    y = grid.top - (draw.row + 0.5) * grid.resolution
    lon, lat = transform(grid.crs, "EPSG:4326", [x], [y])
    r, c = draw.row, draw.col
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon[0], 7), round(lat[0], 7)]},
        "properties": {
            "id": f"{spec.day.isoformat()}-{number:03d}",
            "draw": draw_number,
            "date": spec.day.isoformat(),
            "orbit": spec.orbit,
            "x": x,
            "y": y,
            "stratum": draw.stratum,
            "elevation_band": strata.band_name(draw.band),
            "cell_pixels": draw.cell_pixels,
            "elevation_m": round(float(day_layers.elevation[r, c]), 1),
            "cos_incidence": round(float(day_layers.cos_incidence[r, c]), 3),
            "cast_shadow": bool(day_layers.cast_shadow[r, c]),
            "tree_fraction": round(float(day_layers.tree_fraction[r, c]), 2),
            "in_strata": [name for name in strata.STRATA if date_mask[name][r, c]],
            "chip_scene_id": meta["l1c_scene_ids"][int(source[r, c])],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", type=Path, default=Path("data/domain.geojson"))
    parser.add_argument("--cache", type=Path, required=True, help="folder for the L1C mosaics and strata layers")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--supplement", type=Path, help="points of the earlier draws; draws --draw on top")
    parser.add_argument("--draw", type=int, choices=sorted(SUPPLEMENTS), default=2)
    args = parser.parse_args(argv)
    if args.supplement:
        base = json.loads(args.supplement.read_text(encoding="utf-8"))
        collection = supplement(base, args.draw, args.domain, args.cache, args.out)
    else:
        collection = run(args.domain, args.cache, args.out, args.workers)
    print(f"{len(collection['features'])} points written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
