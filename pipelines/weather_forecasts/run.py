import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import COMMON_HORIZONS_HOURS
from .cycles import select_latest_cycle
from .geo import bbox_from_geojson
from .gfs import GfsClient, accumulation_steps
from .manifest import build_manifest, write_manifest
from .raster import build_accumulated_precipitation


def run(basins: Path, output: Path, keep_downloads: bool) -> Path:
    bbox = bbox_from_geojson(basins)
    client = GfsClient(bbox)
    final_step = COMMON_HORIZONS_HOURS[-1]
    cycle = select_latest_cycle(
        datetime.now(timezone.utc),
        lambda candidate: client.is_complete(candidate, final_step),
    )

    work = output / "work"
    model_root = output / "gfs" / cycle.strftime("%Y%m%dT%HZ")
    precipitation_inputs = {}
    precipitation_files = {}
    phase_files = {}
    for step in accumulation_steps(final_step):
        precipitation_inputs[step] = client.download(
            cycle,
            step,
            ("APCP",),
            work / "precipitation" / f"f{step:03d}.grib2",
        )

    for horizon in COMMON_HORIZONS_HOURS:
        source_files = [precipitation_inputs[step] for step in accumulation_steps(horizon)]
        destination = model_root / f"precipitation_total_f{horizon:03d}.tif"
        build_accumulated_precipitation(source_files, destination)
        precipitation_files[horizon] = destination
        try:
            phase_files[horizon] = client.download(
                cycle,
                horizon,
                ("TMP", "CRAIN", "CSNOW"),
                model_root / f"phase_context_f{horizon:03d}.grib2",
            )
        except (OSError, RuntimeError):
            pass

    manifest = build_manifest(cycle, bbox, output, precipitation_files, phase_files)
    manifest_path = output / "manifest.json"
    write_manifest(manifest, manifest_path)
    if not keep_downloads:
        shutil.rmtree(work)
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--basins", type=Path, default=Path("data/basins.geojson"))
    parser.add_argument("--output", type=Path, default=Path("weather-output"))
    parser.add_argument("--keep-downloads", action="store_true")
    args = parser.parse_args()
    print(run(args.basins, args.output, args.keep_downloads))


if __name__ == "__main__":
    main()
