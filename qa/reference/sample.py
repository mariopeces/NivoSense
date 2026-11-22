"""Draw the stratified points of the reference sample (no labels).

    python -m qa.reference.sample --cache work/reference --out work/reference/points.geojson

For every date in qa/reference/dates.json it reads the L2A scene classes (cloud only, for the
cloud-edge stratum) and sun angles, builds the 10 m L1C mosaic the chips are cut from, and
draws points per stratum and elevation band. Rerunning with the same inputs and seed draws
the same points.
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
from pipelines.s2.stac import group_acquisitions, search_items

from . import layers, strata

DATES_PATH = Path(__file__).with_name("dates.json")
SEED = 20261122
POINTS_PER_STRATUM = 360
# Shadows are traced from terrain up to this far outside the domain.
PAD_M = strata.SHADOW_MAX_DISTANCE_M


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
    for acquisition in group_acquisitions(items):
        if acquisition.day == spec.day and acquisition.orbit == spec.orbit:
            return list(acquisition.items)
    raise ValueError(f"No L2A acquisition on {spec.day} orbit {spec.orbit}")


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
            point_feature(draw, number, spec, meta, day_layers, source, domain.grid, date_mask)
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


def point_feature(
    draw: strata.Draw,
    number: int,
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
    args = parser.parse_args(argv)
    collection = run(args.domain, args.cache, args.out, args.workers)
    print(f"{len(collection['features'])} points written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
