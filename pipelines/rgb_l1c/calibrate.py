"""Measure the reflectance statistics the fixed stretch constants in render.py are taken from.

    python -m pipelines.rgb_l1c.calibrate --s2 work/s2 --domain data/domain.geojson \\
        --date 2025-12-18 --date 2026-02-21 --date 2026-03-25

For each date (a listed pipelines.s2 record) it reads the L1C top-of-atmosphere reflectance of
B04, B03, B02 inside the domain and prints, per band, the dark-object value (0.1th percentile
of all pixels) and the upper percentiles of the pixels under the L2A snow stand-in mask.
"""

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from pipelines.s2.domain import convex_hull, load_domain

from . import qa
from .render import domain_mask, grid_10m, read_reflectance
from .run import observation_dates
from .source import AWS, RGB_ASSETS, find_acquisition

DARK_PERCENTILE = 0.1
SNOW_PERCENTILES = (50.0, 90.0, 99.0, 99.5, 99.9)


def measure(s2_out: Path, domain_path: Path, day: date) -> dict:
    domain = load_domain(domain_path)
    grid = grid_10m(domain.grid)
    record = observation_dates(s2_out, day, day)[0]
    acquisition = find_acquisition(convex_hull(domain.geometries), day, record["orbit"], domain.touches)
    if acquisition is None:
        raise RuntimeError(f"No L1C for {day}")
    reflectance = read_reflectance(acquisition, grid, AWS)
    inside = domain_mask(domain.geometries, grid)
    l2a, scl = qa.read_l2a(s2_out / record["date"] / record["orbit"])
    snow = np.repeat(np.repeat(qa.snow_mask(l2a, scl) & domain.mask, 2, axis=0), 2, axis=1) & inside
    result: dict = {"date": record["date"], "orbit": record["orbit"], "snow_pixels_10m": int(snow.sum())}
    for asset in RGB_ASSETS:
        band = reflectance[asset]
        valid = inside & ~np.isnan(band)
        snow_values = band[snow & valid]
        result[asset] = {
            "dark": round(float(np.percentile(band[valid], DARK_PERCENTILE)), 4),
            "snow": {
                str(p): round(float(np.percentile(snow_values, p)), 4) if snow_values.size else None
                for p in SNOW_PERCENTILES
            },
        }
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--s2", type=Path, required=True)
    parser.add_argument("--domain", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, action="append", required=True)
    args = parser.parse_args(argv)
    for day in args.date:
        print(json.dumps(measure(args.s2, args.domain, day)))


if __name__ == "__main__":
    main()
