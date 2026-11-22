import json
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from pipelines.weather_forecasts import aemet
from pipelines.weather_forecasts.config import (
    COARSE_MODELS_ALLOWED,
    COMMON_HORIZONS_HOURS,
    MAX_RESOLUTION_KM,
)
from pipelines.weather_forecasts.cycles import select_latest_cycle
from pipelines.weather_forecasts.manifest import Field, ModelOutput, build_manifest

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

    def test_every_published_model_is_high_resolution(self):
        for path in (Path("frontend/public/weather/manifest.json"),):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for model in payload["models"]:
                if model["id"] not in COARSE_MODELS_ALLOWED:
                    self.assertLess(model["resolution_km"], MAX_RESOLUTION_KM, model["id"])
        self.assertEqual(COARSE_MODELS_ALLOWED, {"weathernext"})

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

    def _files(self, root, name, horizons):
        files, images = {}, {}
        for horizon in horizons:
            files[horizon] = root / f"{name}-{horizon}.tif"
            files[horizon].write_bytes(f"{name}-{horizon}".encode())
            images[horizon] = root / f"{name}-{horizon}.png"
            images[horizon].write_bytes(f"image-{name}-{horizon}".encode())
        return files, images

    def _model(self, root, model_id, resolution_km, horizons=COMMON_HORIZONS_HOURS):
        fields = {}
        for variable, units in (("precipitation_total", "mm"), ("temperature_2m", "°C")):
            files, images = self._files(root, f"{model_id}-{variable}", horizons)
            fields[variable] = Field(
                files,
                [-4.0, 36.0, -2.0, 38.0],
                units,
                images,
                0.0,
                42.0,
                {h: 1.0 for h in horizons},
                {h: 0.0 for h in horizons},
                missing_reason="Forecast range is 48 h",
            )
        return ModelOutput(
            id=model_id,
            name=model_id.upper(),
            attribution="Test",
            source="https://example.com/",
            grid_degrees=0.025,
            resolution_km=resolution_km,
            cycle=datetime(2026, 10, 18, 6, tzinfo=timezone.utc),
            fields=fields,
            missing_reasons={"wind_speed_10m": "Not provided"},
        )

    def test_manifest_matches_schema_and_marks_missing_horizons_and_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model = self._model(root, "aemet", 2.5, (24, 48))
            payload = build_manifest("test-region", (-4.0, 36.0, -2.0, 38.0), root, [model], [])
            schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
            horizons = payload["models"][0]["horizons"]
            self.assertEqual(payload["models"][0]["resolution_km"], 2.5)
            self.assertEqual(horizons["24"]["temperature_2m"]["units"], "°C")
            self.assertEqual(horizons["24"]["precipitation_total"]["visualization"]["region_max"], 1.0)
            self.assertEqual(
                horizons["120"]["precipitation_total"],
                {"available": False, "reason": "Forecast range is 48 h"},
            )
            self.assertEqual(
                horizons["24"]["wind_speed_10m"], {"available": False, "reason": "Not provided"}
            )

    def test_every_model_in_the_manifest_is_finer_than_the_limit_except_the_granted_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fine = self._model(root, "aemet", 2.5)
            exception = self._model(root, "weathernext", 10.0)
            payload = build_manifest("r", (-4.0, 36.0, -2.0, 38.0), root, [fine, exception], [])
            for model in payload["models"]:
                if model["id"] not in COARSE_MODELS_ALLOWED:
                    self.assertLess(model["resolution_km"], MAX_RESOLUTION_KM)
            for model_id, resolution in (("gfs", 25.0), ("ecmwf", 28.0), ("coarse", MAX_RESOLUTION_KM)):
                with self.assertRaises(ValueError):
                    build_manifest("r", (-4.0, 36.0, -2.0, 38.0), root, [self._model(root, model_id, resolution)], [])

    def test_aemet_decode_instant_uses_class_midpoints(self):
        try:
            import numpy  # noqa: F401
            import rasterio
        except ImportError:
            self.skipTest("Raster dependencies are not installed")

        legend = {
            "Producto": "11",
            "Lista RGBA": [
                {"Valores": [10, ""], "RGBA": ["200", "0", "0", "255"]},
                {"Valores": [8, 10], "RGBA": ["255", "128", "0", "255"]},
                {"Valores": [-2, 0], "RGBA": ["255", "255", "255", "255"]},
            ],
        }
        import numpy as np
        from rasterio.transform import from_origin

        array = np.array(
            [[[200, 0, 0, 255], [250, 130, 0, 255]], [[255, 255, 255, 255], [255, 255, 255, 0]]],
            dtype="uint8",
        ).transpose(2, 0, 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.tif"
            with rasterio.open(
                path, "w", driver="GTiff", width=2, height=2, count=4, dtype="uint8",
                crs="EPSG:4326", transform=from_origin(-4.0, 38.0, 0.5, 0.5),
            ) as dataset:
                dataset.write(array)
                dataset.update_tags(ESCALA=str(legend))
            estimate, _ = aemet.decode_instant(path.read_bytes(), (-4.0, 37.0, -3.0, 38.0))
        self.assertEqual(estimate[0].tolist(), [10.0, 9.0])
        self.assertEqual(estimate[1][0], -1.0)
        self.assertTrue(np.isnan(estimate[1][1]))

    def test_weathernext_regional_fields_convert_units_and_accumulate(self):
        try:
            import numpy as np
            import xarray as xr
        except ImportError:
            self.skipTest("xarray is not installed")
        from pipelines.weather_forecasts import weathernext

        lat = np.round(np.arange(36.0, 38.01, 0.1), 1)
        lon = np.round(np.arange(355.0, 358.01, 0.1), 1)
        lead = np.arange(1, 25) * np.timedelta64(1, "h")
        shape = (lead.size, lat.size, lon.size)
        dims = ("lead_time", "lat_0p1", "lon_0p1")
        dataset = xr.Dataset(
            {
                "temperature_2m_mean": (dims, np.full(shape, 283.15, dtype="float32")),
                "wind_speed_10m_mean": (dims, np.full(shape, 10.0, dtype="float32")),
                "total_precipitation_1hr_mean": (dims, np.full(shape, 0.0005, dtype="float32")),
            },
            coords={"lead_time": lead, "lat_0p1": lat, "lon_0p1": lon},
        )
        fields, transform = weathernext.regional_fields(dataset, (-3.6433, 36.9129, -2.5885, 37.2532), (6, 24))
        self.assertTrue(np.allclose(fields["temperature_2m"][24], 10.0))
        self.assertTrue(np.allclose(fields["wind_speed_10m"][6], 36.0))
        self.assertTrue(np.allclose(fields["precipitation_total"][6], 3.0))
        self.assertTrue(np.allclose(fields["precipitation_total"][24], 12.0))
        rows, columns = fields["temperature_2m"][24].shape
        self.assertAlmostEqual(transform.a, 0.1)
        self.assertLessEqual(transform.c, -3.6433)
        self.assertGreaterEqual(transform.c + columns * 0.1, -2.5885)
        self.assertGreaterEqual(transform.f, 37.2532)
        self.assertLessEqual(transform.f - rows * 0.1, 36.9129)

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
            import numpy  # noqa: F401
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
