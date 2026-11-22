import argparse
import shutil
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from ..region import load_region
from . import aemet, weathernext
from .config import COMMON_HORIZONS_HOURS, MIN_SCALE_MM, VARIABLES
from .cycles import select_latest_cycle
from .manifest import Field, ModelOutput, build_manifest, write_manifest
from .raster import (
    FIXED_SCALES,
    build_classified_field,
    build_field_image,
    build_grid_field,
    raster_bounds_and_range,
)

FINAL_HOURS = COMMON_HORIZONS_HOURS[-1]
AEMET_HORIZONS = tuple(h for h in COMMON_HORIZONS_HOURS if h <= aemet.MAX_HORIZON_HOURS)
# Shown to users: AEMET publishes colour-classified images, not the physical field.
AEMET_NOTE = "Reconstruido a partir de los mapas por clases de color de AEMET: punto medio de cada clase"


def build_aemet(bbox: tuple[float, float, float, float], output: Path, work: Path) -> ModelOutput:
    archive_path = aemet.download_archive(work / "aemet" / "harmonie_pb.tar.gz")
    reason = f"Forecast range is {aemet.MAX_HORIZON_HOURS} h"
    with tarfile.open(archive_path) as archive:
        cycle = aemet.run_cycle(archive)
        decoded = {}
        for end, name in aemet.precipitation_windows(archive, cycle).items():
            member = archive.extractfile(name)
            if member is None:
                raise RuntimeError(f"AEMET archive entry {name} is not a file")
            decoded[end] = aemet.decode_window(member.read(), bbox)
        instant: dict[str, dict[int, tuple]] = {}
        for variable, product in aemet.INSTANT_PRODUCTS.items():
            members = aemet.instant_members(archive, cycle, product)
            instant[variable] = {}
            for horizon in AEMET_HORIZONS:
                handle = archive.extractfile(members[horizon]) if horizon in members else None
                if handle is None:
                    raise RuntimeError(f"AEMET archive lacks {variable} at {horizon} h")
                instant[variable][horizon] = aemet.decode_instant(handle.read(), bbox)

    root = output / "aemet" / cycle.strftime("%Y%m%dT%HZ")
    transform = decoded[aemet.WINDOW_HOURS][3]
    precipitation = {}
    for horizon in AEMET_HORIZONS:
        destination = root / f"precipitation_total_f{horizon:03d}.tif"
        build_classified_field(
            [decoded[end][:3] for end in range(aemet.WINDOW_HOURS, horizon + 1, aemet.WINDOW_HOURS)],
            transform,
            destination,
        )
        precipitation[horizon] = destination
    bounds, _, _ = raster_bounds_and_range(precipitation[max(precipitation)])
    fields = {
        "precipitation_total": Field(
            precipitation,
            bounds,
            "mm",
            missing_reason=reason,
            note=AEMET_NOTE,
        )
    }
    for variable, units in (("temperature_2m", "°C"), ("wind_speed_10m", "km/h")):
        files = {}
        for horizon in AEMET_HORIZONS:
            estimate, field_transform = instant[variable][horizon]
            destination = root / f"{variable}_f{horizon:03d}.tif"
            build_grid_field(estimate, field_transform, destination, f"{variable}_class_midpoint", units)
            files[horizon] = destination
        fields[variable] = Field(
            files,
            raster_bounds_and_range(files[max(files)])[0],
            units,
            missing_reason=reason,
            note=AEMET_NOTE,
        )
    return ModelOutput(
        id="aemet",
        name="AEMET HARMONIE-AROME",
        attribution="AEMET, HARMONIE-AROME. Use authorised citing AEMET as author",
        source="https://www.aemet.es/es/eltiempo/prediccion/modelosnumericos/harmonie_arome",
        grid_degrees=0.025,
        resolution_km=2.5,
        cycle=cycle,
        fields=fields,
    )


def build_weathernext(bbox: tuple[float, float, float, float], output: Path, work: Path) -> ModelOutput:
    cycle = select_latest_cycle(
        datetime.now(timezone.utc),
        lambda candidate: weathernext.is_complete(candidate, FINAL_HOURS),
    )
    arrays, transform = weathernext.regional_fields(
        weathernext.open_run(cycle), bbox, COMMON_HORIZONS_HOURS
    )
    root = output / "weathernext" / cycle.strftime("%Y%m%dT%HZ")
    fields = {}
    for variable, (_, _, _, units) in weathernext.SOURCES.items():
        files = {}
        for horizon, values in arrays[variable].items():
            destination = root / f"{variable}_f{horizon:03d}.tif"
            build_grid_field(values, transform, destination, f"{variable}_ensemble_mean", units)
            files[horizon] = destination
        fields[variable] = Field(
            files,
            raster_bounds_and_range(files[FINAL_HOURS])[0],
            units,
            note="Media del conjunto de 64 miembros" if variable == "precipitation_total" else None,
        )
    return ModelOutput(
        id="weathernext",
        name="WeatherNext 3 (Google DeepMind)",
        attribution=weathernext.ATTRIBUTION,
        source=weathernext.SOURCE_URL,
        grid_degrees=weathernext.GRID_DEGREES,
        resolution_km=10.0,
        cycle=cycle,
        fields=fields,
        experimental=True,
    )


def render_images(models: list[ModelOutput]) -> None:
    for variable in VARIABLES:
        fields = [model.fields[variable] for model in models if variable in model.fields]
        if not fields:
            continue
        for item in fields:
            for horizon, source in item.files.items():
                _, minimum, maximum = raster_bounds_and_range(source)
                item.minima[horizon], item.maxima[horizon] = minimum, maximum
        if variable in FIXED_SCALES:
            scale_min, scale_max = FIXED_SCALES[variable]
        else:
            scale_min = 0.0
            scale_max = max(MIN_SCALE_MM, *(max(item.maxima.values()) for item in fields))
        for item in fields:
            item.scale_min, item.scale_max = scale_min, scale_max
            for horizon, source in item.files.items():
                image = source.with_suffix(".png")
                build_field_image(source, image, scale_min, scale_max, variable)
                item.images[horizon] = image


def run(region_file: Path, output: Path, keep_downloads: bool) -> Path:
    region = load_region(region_file)
    work = output / "work"
    models = []
    unavailable = []
    for model_id, label, build in (
        ("aemet", "AEMET HARMONIE-AROME", build_aemet),
        ("weathernext", "WeatherNext 3 (Google DeepMind)", build_weathernext),
    ):
        try:
            models.append(build(region.bbox, output, work))
        except Exception as error:  # noqa: BLE001 - the remote store raises its own error types (a 403 for an identity that is not allowlisted)
            print(f"::warning::{model_id} forecast skipped: {type(error).__name__}: {error}", file=sys.stderr)
            # WeatherNext needs an allowlisted identity; until it works the site simply does not list it.
            if model_id != "weathernext":
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
