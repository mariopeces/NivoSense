import argparse
import shutil
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from ..region import load_region
from . import aemet
from .config import COMMON_HORIZONS_HOURS, MIN_SCALE_MM, UNAVAILABLE_MODELS
from .cycles import select_latest_cycle
from .ecmwf import PARAMETERS, EcmwfClient
from .gfs import GfsClient, accumulation_steps
from .manifest import Field, ModelOutput, build_manifest, write_manifest
from .raster import (
    build_accumulated_precipitation,
    build_classified_field,
    build_field_image,
    build_regional_field,
    raster_bounds_and_maximum,
)

FINAL_HOURS = COMMON_HORIZONS_HOURS[-1]


def build_gfs(bbox, output: Path, work: Path) -> ModelOutput:
    west, south, east, north = bbox
    # The NOMADS subset only returns cells whose centres fall inside the box.
    client = GfsClient((west - 0.25, south - 0.25, east + 0.25, north + 0.25))
    cycle = select_latest_cycle(
        datetime.now(timezone.utc),
        lambda candidate: client.is_complete(candidate, FINAL_HOURS),
    )
    root = output / "gfs" / cycle.strftime("%Y%m%dT%HZ")
    inputs = {
        step: client.download(
            cycle, step, ("APCP",), work / "gfs" / f"apcp_f{step:03d}.grib2"
        )
        for step in accumulation_steps(FINAL_HOURS)
    }
    precipitation = {}
    phase_files = {}
    for horizon in COMMON_HORIZONS_HOURS:
        destination = root / f"precipitation_total_f{horizon:03d}.tif"
        build_accumulated_precipitation(
            [inputs[step] for step in accumulation_steps(horizon)], destination
        )
        precipitation[horizon] = destination
        try:
            phase_files[horizon] = client.download(
                cycle,
                horizon,
                ("TMP", "CRAIN", "CSNOW"),
                root / f"phase_context_f{horizon:03d}.grib2",
            )
        except (OSError, RuntimeError):
            pass

    bounds, _ = raster_bounds_and_maximum(precipitation[FINAL_HOURS])
    return ModelOutput(
        id="gfs",
        name="GFS",
        attribution="NOAA NCEP Global Forecast System",
        source="https://nomads.ncep.noaa.gov/",
        grid_degrees=0.25,
        cycle=cycle,
        precipitation=Field(precipitation, bounds),
        snowfall_reason="Instantaneous phase indicators do not provide an accumulated snowfall field",
        phase_files=phase_files,
    )


def build_ecmwf(bbox, output: Path, work: Path) -> ModelOutput:
    client = EcmwfClient()
    cycle = select_latest_cycle(
        datetime.now(timezone.utc),
        lambda candidate: client.is_complete(candidate, FINAL_HOURS),
        stride_hours=12,
    )
    root = output / "ecmwf" / cycle.strftime("%Y%m%dT%HZ")
    fields = {}
    for variable, parameter in PARAMETERS.items():
        files = {}
        for horizon in COMMON_HORIZONS_HOURS:
            grib = client.download(
                cycle,
                horizon,
                parameter,
                work / "ecmwf" / f"{parameter}_f{horizon:03d}.grib2",
            )
            destination = root / f"{variable}_f{horizon:03d}.tif"
            build_regional_field(grib, bbox, destination, 1000.0, f"{variable}_accumulated_mm")
            files[horizon] = destination
        bounds, _ = raster_bounds_and_maximum(files[FINAL_HOURS])
        fields[variable] = Field(files, bounds)

    return ModelOutput(
        id="ecmwf",
        name="ECMWF IFS",
        attribution="ECMWF open data, CC BY 4.0",
        source="https://www.ecmwf.int/en/forecasts/datasets/open-data",
        grid_degrees=0.25,
        cycle=cycle,
        precipitation=fields["precipitation_total"],
        snowfall=fields["snowfall"],
    )


def build_aemet(bbox, output: Path, work: Path) -> ModelOutput:
    archive_path = aemet.download_archive(work / "aemet" / "harmonie_pb.tar.gz")
    with tarfile.open(archive_path) as archive:
        cycle = aemet.run_cycle(archive)
        decoded = {
            end: aemet.decode_window(archive.extractfile(name).read(), bbox)
            for end, name in aemet.precipitation_windows(archive, cycle).items()
        }
    root = output / "aemet" / cycle.strftime("%Y%m%dT%HZ")
    transform = decoded[aemet.WINDOW_HOURS][3]
    files = {}
    for horizon in COMMON_HORIZONS_HOURS:
        if horizon > aemet.MAX_HORIZON_HOURS:
            continue
        destination = root / f"precipitation_total_f{horizon:03d}.tif"
        build_classified_field(
            [
                decoded[end][:3]
                for end in range(aemet.WINDOW_HOURS, horizon + 1, aemet.WINDOW_HOURS)
            ],
            transform,
            destination,
        )
        files[horizon] = destination
    bounds, _ = raster_bounds_and_maximum(files[max(files)])
    return ModelOutput(
        id="aemet",
        name="AEMET HARMONIE-AROME",
        attribution="AEMET, HARMONIE-AROME. Use authorised citing AEMET as author",
        source="https://www.aemet.es/es/eltiempo/prediccion/modelosnumericos/harmonie_arome",
        grid_degrees=0.025,
        cycle=cycle,
        precipitation=Field(
            files,
            bounds,
            missing_reason=f"Forecast range is {aemet.MAX_HORIZON_HOURS} h",
            note="Reconstructed from AEMET colour-classified maps: class midpoints, bounds in bands 2 and 3",
        ),
        snowfall_reason="AEMET publishes no snowfall field",
    )


def render_images(models: list[ModelOutput]) -> None:
    for variable in ("precipitation_total", "snowfall"):
        fields = [
            item
            for item in (getattr(model, "precipitation" if variable == "precipitation_total" else "snowfall") for model in models)
            if item
        ]
        if not fields:
            continue
        for item in fields:
            item.maxima = {
                horizon: raster_bounds_and_maximum(source)[1]
                for horizon, source in item.files.items()
            }
        scale_max = max(MIN_SCALE_MM, *(max(item.maxima.values()) for item in fields))
        for item in fields:
            item.scale_max_mm = scale_max
            for horizon, source in item.files.items():
                image = source.with_suffix(".png")
                build_field_image(source, image, scale_max, variable)
                item.images[horizon] = image


def run(region_file: Path, output: Path, keep_downloads: bool) -> Path:
    region = load_region(region_file)
    work = output / "work"
    models = []
    unavailable = [dict(item) for item in UNAVAILABLE_MODELS]
    for model_id, label, build in (
        ("gfs", "GFS", build_gfs),
        ("ecmwf", "ECMWF IFS", build_ecmwf),
        ("aemet", "AEMET HARMONIE-AROME", build_aemet),
    ):
        try:
            models.append(build(region.bbox, output, work))
        except (OSError, RuntimeError, ValueError) as error:
            print(f"::warning::{model_id} forecast skipped: {error}", file=sys.stderr)
            unavailable.append(
                {"id": model_id, "name": label, "reason": f"Skipped in the latest run: {error}"}
            )
    if not models:
        raise RuntimeError("No forecast model produced data")

    render_images(models)
    manifest_path = output / "manifest.json"
    write_manifest(
        build_manifest(region.id, region.bbox, output, models, unavailable), manifest_path
    )
    if not keep_downloads:
        shutil.rmtree(work, ignore_errors=True)
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", type=Path, default=Path("regions/sierra-nevada.json"))
    parser.add_argument("--output", type=Path, default=Path("weather-output"))
    parser.add_argument("--keep-downloads", action="store_true")
    args = parser.parse_args()
    print(run(args.region, args.output, args.keep_downloads))


if __name__ == "__main__":
    main()
