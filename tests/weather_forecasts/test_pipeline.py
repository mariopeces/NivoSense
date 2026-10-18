import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from pipelines.weather_forecasts.config import COMMON_HORIZONS_HOURS
from pipelines.weather_forecasts.cycles import select_latest_cycle
from pipelines.weather_forecasts.ecmwf import EcmwfClient
from pipelines.weather_forecasts.gfs import accumulation_steps
from pipelines.weather_forecasts.manifest import Field, ModelOutput, build_manifest
from pipelines.weather_forecasts.raster import (
    build_accumulated_precipitation,
    build_regional_field,
)


FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = Path("pipelines/weather_forecasts/manifest.schema.json")


class ForecastPipelineTests(unittest.TestCase):
    def test_empty_published_manifest_matches_schema(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        payload = json.loads(
            Path("frontend/public/weather/manifest.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
        self.assertEqual(payload["models"], [])

    def test_common_horizons(self):
        self.assertEqual(COMMON_HORIZONS_HOURS, (24, 48, 72, 120))

    def test_selects_latest_complete_cycle_from_fixture(self):
        fixture = json.loads((FIXTURES / "cycle_statuses.json").read_text(encoding="utf-8"))
        now = datetime.fromisoformat(fixture["now"].replace("Z", "+00:00"))
        complete = {
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            for value in fixture["complete_cycles"]
        }
        selected = select_latest_cycle(now, complete.__contains__)
        self.assertEqual(selected, datetime(2026, 10, 18, 6, tzinfo=timezone.utc))

    def test_accumulation_steps_use_disjoint_six_hour_windows(self):
        self.assertEqual(accumulation_steps(24), (6, 12, 18, 24))
        self.assertEqual(accumulation_steps(120), tuple(range(6, 121, 6)))
        self.assertEqual(sum(6 for _ in accumulation_steps(120)), 120)

    def test_accumulated_raster_sums_intervals(self):
        try:
            import numpy as np
            import rasterio
            from rasterio.transform import from_origin
        except ImportError:
            self.skipTest("Raster dependencies are not installed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = {
                "driver": "GTiff",
                "width": 16,
                "height": 16,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:4326",
                "transform": from_origin(0, 1, 0.25, 0.25),
            }
            inputs = []
            for index, value in enumerate((1.25, 2.5)):
                path = root / f"input-{index}.tif"
                with rasterio.open(path, "w", **profile) as dataset:
                    dataset.write(np.full((16, 16), value, dtype="float32"), 1)
                inputs.append(path)
            destination = root / "total.tif"
            build_accumulated_precipitation(inputs, destination)
            with rasterio.open(destination) as dataset:
                self.assertTrue(np.allclose(dataset.read(1), 3.75))
                self.assertEqual(dataset.descriptions[0], "precipitation_total_accumulated_mm")

    def test_ecmwf_cycles_use_twelve_hour_stride(self):
        selected = select_latest_cycle(
            datetime(2026, 10, 18, 17, 30, tzinfo=timezone.utc),
            lambda cycle: cycle.hour == 0,
            stride_hours=12,
        )
        self.assertEqual(selected, datetime(2026, 10, 18, 0, tzinfo=timezone.utc))

    def test_ecmwf_index_selects_surface_parameters_with_byte_ranges(self):
        lines = [
            {"levtype": "sfc", "param": "tp", "_offset": 0, "_length": 10},
            {"levtype": "pl", "param": "tp", "_offset": 10, "_length": 5},
            {"levtype": "sfc", "param": "sf", "_offset": 15, "_length": 7},
        ]
        client = EcmwfClient()
        payload = "\n".join(json.dumps(line) for line in lines).encode()
        client._read = lambda url, headers=None: payload
        cycle = datetime(2026, 10, 18, tzinfo=timezone.utc)
        self.assertEqual(client.index(cycle, 24), {"tp": (0, 10), "sf": (15, 7)})
        self.assertTrue(client.is_complete(cycle, 24))

    def test_ecmwf_regional_field_converts_metres_and_covers_region(self):
        try:
            import eccodes
            import numpy as np
            import rasterio
        except ImportError:
            self.skipTest("GRIB dependencies are not installed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            message = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
            for key, value in {
                "Ni": 8,
                "Nj": 6,
                "latitudeOfFirstGridPointInDegrees": 40.0,
                "latitudeOfLastGridPointInDegrees": 37.5,
                "longitudeOfFirstGridPointInDegrees": 356.0,
                "longitudeOfLastGridPointInDegrees": 357.75,
                "iDirectionIncrementInDegrees": 0.25,
                "jDirectionIncrementInDegrees": 0.5,
            }.items():
                eccodes.codes_set(message, key, value)
            grid = np.arange(48, dtype="float64").reshape(6, 8) / 1000
            eccodes.codes_set_values(message, grid.ravel())
            source = root / "field.grib2"
            with source.open("wb") as handle:
                eccodes.codes_write(message, handle)
            eccodes.codes_release(message)

            destination = root / "field.tif"
            bbox = (-3.9, 38.1, -3.2, 39.4)
            build_regional_field(source, bbox, destination, 1000.0, "test_mm")
            with rasterio.open(destination) as dataset:
                data = dataset.read(1)
                self.assertLessEqual(dataset.bounds.left, bbox[0])
                self.assertGreaterEqual(dataset.bounds.right, bbox[2])
                self.assertLessEqual(dataset.bounds.bottom, bbox[1])
                self.assertGreaterEqual(dataset.bounds.top, bbox[3])
                self.assertEqual(dataset.descriptions[0], "test_mm")
            # Longitudes 356.0..357.75 are -4.0..-2.25 and the region starts at column 0.
            self.assertTrue(np.allclose(data[0, 0], 1 * 8 + 0))

    def test_manifest_matches_schema_and_separates_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def field(name, bounds):
                files, images = {}, {}
                for horizon in COMMON_HORIZONS_HOURS:
                    files[horizon] = root / f"{name}-{horizon}.tif"
                    files[horizon].write_bytes(f"{name}-{horizon}".encode())
                    images[horizon] = root / f"{name}-{horizon}.png"
                    images[horizon].write_bytes(f"image-{name}-{horizon}".encode())
                return Field(
                    files,
                    bounds,
                    images,
                    42.0,
                    {horizon: 1.0 for horizon in COMMON_HORIZONS_HOURS},
                )

            gfs = ModelOutput(
                id="gfs",
                name="GFS",
                attribution="NOAA",
                source="https://nomads.ncep.noaa.gov/",
                grid_degrees=0.25,
                cycle=datetime(2026, 10, 18, 6, tzinfo=timezone.utc),
                precipitation=field("gfs", [-4.0, 36.0, -2.0, 38.0]),
                snowfall_reason="No accumulated snowfall field",
            )
            ecmwf = ModelOutput(
                id="ecmwf",
                name="ECMWF IFS",
                attribution="ECMWF",
                source="https://www.ecmwf.int/en/forecasts/datasets/open-data",
                grid_degrees=0.25,
                cycle=datetime(2026, 10, 18, 0, tzinfo=timezone.utc),
                precipitation=field("ecmwf-tp", [-4.0, 36.0, -2.0, 38.5]),
                snowfall=field("ecmwf-sf", [-4.0, 36.0, -2.0, 38.5]),
            )
            payload = build_manifest((-4.0, 36.0, -2.0, 38.0), root, [gfs, ecmwf])
            schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
            self.assertEqual(payload["common_horizons_hours"], [24, 48, 72, 120])
            by_id = {model["id"]: model for model in payload["models"]}
            for horizon in by_id["gfs"]["horizons"].values():
                self.assertFalse(horizon["snowfall"]["available"])
                self.assertEqual(horizon["precipitation_total"]["units"], "mm")
            for horizon in by_id["ecmwf"]["horizons"].values():
                self.assertTrue(horizon["snowfall"]["available"])
                self.assertEqual(horizon["snowfall"]["units"], "mm")
                self.assertEqual(horizon["snowfall"]["basis"], "water_equivalent")
            self.assertEqual(
                {item["id"] for item in payload["unavailable_models"]},
                {"weathernext", "aemet"},
            )


if __name__ == "__main__":
    unittest.main()
