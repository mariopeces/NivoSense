import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from pipelines.weather_forecasts.config import COMMON_HORIZONS_HOURS
from pipelines.weather_forecasts.cycles import select_latest_cycle
from pipelines.weather_forecasts.gfs import accumulation_steps
from pipelines.weather_forecasts.manifest import build_manifest
from pipelines.weather_forecasts.raster import build_accumulated_precipitation


FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = Path("pipelines/weather_forecasts/manifest.schema.json")


class ForecastPipelineTests(unittest.TestCase):
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

    def test_accumulation_steps_cover_each_three_hour_window(self):
        self.assertEqual(accumulation_steps(24), tuple(range(3, 25, 3)))
        self.assertEqual(accumulation_steps(120), tuple(range(3, 121, 3)))
        self.assertEqual(sum(3 for _ in accumulation_steps(120)), 120)

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

    def test_manifest_matches_schema_and_declares_snow_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            precipitation = {}
            phase = {}
            for horizon in COMMON_HORIZONS_HOURS:
                precipitation[horizon] = root / f"precip-{horizon}.tif"
                precipitation[horizon].write_bytes(f"precip-{horizon}".encode())
                phase[horizon] = root / f"phase-{horizon}.grib2"
                phase[horizon].write_bytes(f"phase-{horizon}".encode())
            payload = build_manifest(
                datetime(2026, 10, 18, 6, tzinfo=timezone.utc),
                (-4.0, 36.0, -2.0, 38.0),
                root,
                precipitation,
                phase,
            )
            schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
            self.assertEqual(payload["common_horizons_hours"], [24, 48, 72, 120])
            for horizon in payload["models"][0]["horizons"].values():
                self.assertTrue(horizon["precipitation_total"]["available"])
                self.assertFalse(horizon["snowfall"]["available"])


if __name__ == "__main__":
    unittest.main()
