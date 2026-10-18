import json
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from pipelines.weather_forecasts.config import COMMON_HORIZONS_HOURS
from pipelines.weather_forecasts.cycles import select_latest_cycle
from pipelines.weather_forecasts import aemet
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
            payload = build_manifest(
                "test-region",
                (-4.0, 36.0, -2.0, 38.0),
                root,
                [gfs, ecmwf],
                [{"id": "weathernext", "name": "WeatherNext 3", "reason": "No access"}],
            )
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
            self.assertEqual(payload["region"]["id"], "test-region")
            self.assertEqual(
                [item["id"] for item in payload["unavailable_models"]], ["weathernext"]
            )

    def test_manifest_marks_horizons_beyond_model_range_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files, images = {}, {}
            for horizon in (24, 48):
                files[horizon] = root / f"f{horizon}.tif"
                files[horizon].write_bytes(b"tif")
                images[horizon] = root / f"f{horizon}.png"
                images[horizon].write_bytes(b"png")
            model = ModelOutput(
                id="short",
                name="Short range",
                attribution="Test",
                source="https://example.com/",
                grid_degrees=0.025,
                cycle=datetime(2026, 10, 18, 6, tzinfo=timezone.utc),
                precipitation=Field(
                    files,
                    [0, 0, 1, 1],
                    images,
                    5.0,
                    {24: 1.0, 48: 2.0},
                    missing_reason="Forecast range is 48 h",
                    note="Classified",
                ),
                snowfall_reason="No snowfall field",
            )
            payload = build_manifest("test-region", (0, 0, 1, 1), root, [model], [])
            schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
            horizons = payload["models"][0]["horizons"]
            self.assertTrue(horizons["48"]["precipitation_total"]["available"])
            self.assertEqual(horizons["48"]["precipitation_total"]["note"], "Classified")
            self.assertEqual(
                horizons["120"]["precipitation_total"],
                {"available": False, "reason": "Forecast range is 48 h"},
            )

    def _aemet_legend(self):
        return {
            "Producto": "61",
            "Lista RGBA": [
                {"Valores": [10, ""], "RGBA": ["0", "153", "0", "255"]},
                {"Valores": [2, 5], "RGBA": ["0", "204", "128", "255"]},
                {"Valores": [0.5, 1.0], "RGBA": ["176", "224", "230", "255"]},
                {"Valores": [0.0, 0.5], "RGBA": ["19", "49", "52", "0"]},
            ],
        }

    def _aemet_raster(self, root, rows, name="field.tif"):
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        array = np.array(rows, dtype="uint8").transpose(2, 0, 1)
        path = root / name
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=array.shape[2],
            height=array.shape[1],
            count=4,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(-4.0, 38.0, 0.5, 0.5),
        ) as dataset:
            dataset.write(array)
            dataset.update_tags(ESCALA=str(self._aemet_legend()))
        return path

    def test_aemet_decode_assigns_nearest_legend_class(self):
        try:
            import numpy as np
            import rasterio  # noqa: F401
        except ImportError:
            self.skipTest("Raster dependencies are not installed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transparent = [19, 49, 52, 0]
            rows = [
                [[0, 204, 128, 255], [3, 200, 130, 250], transparent, [0, 153, 0, 255]],
                [[176, 224, 230, 255], [0, 0, 0, 10], [0, 150, 2, 255], transparent],
            ]
            data = self._aemet_raster(root, rows).read_bytes()
            lower, upper, estimate, _, _ = aemet.decode_window(data, (-4.0, 37.0, -2.0, 38.0))
            self.assertEqual(lower.tolist(), [[2, 2, 0, 10], [0.5, 0, 10, 0]])
            self.assertEqual(upper.tolist(), [[5, 5, 0.5, 10], [1, 0.5, 10, 0.5]])
            self.assertEqual(estimate.tolist(), [[3.5, 3.5, 0, 10], [0.75, 0, 10, 0]])

    def test_aemet_decode_rejects_regions_outside_the_domain(self):
        try:
            import rasterio  # noqa: F401
        except ImportError:
            self.skipTest("Raster dependencies are not installed")

        with tempfile.TemporaryDirectory() as directory:
            data = self._aemet_raster(
                Path(directory), [[[19, 49, 52, 0]] * 4] * 2
            ).read_bytes()
            with self.assertRaises(RuntimeError):
                aemet.decode_window(data, (10.0, 40.0, 11.0, 41.0))

    def test_aemet_archive_cycle_and_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "archive.tar.gz"
            start = datetime(2026, 10, 18, 7, tzinfo=timezone.utc)
            with tarfile.open(path, "w:gz") as archive:
                for hour in range(48):
                    valid = start + timedelta(hours=hour)
                    stamp = valid.isoformat()
                    for suffix in ("11.tif", "61_1HH.tif") + (
                        ("61_6HH.tif",) if valid.hour % 6 == 0 else ()
                    ):
                        member = tarfile.TarInfo(f"down_{stamp}_{suffix}")
                        archive.addfile(member)
            with tarfile.open(path) as archive:
                cycle = aemet.run_cycle(archive)
                self.assertEqual(cycle, datetime(2026, 10, 18, 6, tzinfo=timezone.utc))
                windows = aemet.precipitation_windows(archive, cycle)
            self.assertEqual(sorted(windows), list(range(6, 49, 6)))


if __name__ == "__main__":
    unittest.main()
