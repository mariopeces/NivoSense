import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np

from pipelines.catalog import LocalStorage, publish, rebuild_index
from pipelines.snow_gapfill import fill as f
from pipelines.snow_gapfill import run
from pipelines.snow_obs.classify import CLOUD, NO_SNOW, NODATA, SNOW

LEFT, TOP = 460000.0, 4100000.0
ROWS, COLS = 40, 120
ELEVATION = np.tile(1000.0 + 15.0 * np.arange(COLS, dtype="float32"), (ROWS, 1))


def write(path: Path, bands: np.ndarray, dtype: str, nodata: float | None) -> Path:
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(
        path, "w", driver="GTiff", width=COLS, height=ROWS, count=bands.shape[0], dtype=dtype,
        crs="EPSG:32630", transform=from_origin(LEFT, TOP, 20, 20), nodata=nodata,
    ) as dst:
        dst.write(bands.astype(dtype))
    return path


def publish_observation(storage: LocalStorage, folder: Path, day: str, classes: np.ndarray) -> None:
    data = write(folder / f"{day}.tif", np.stack([classes, np.zeros_like(classes), np.zeros_like(classes)]),
                 "uint8", 255)
    display = write(folder / f"{day}-rgba.tif", np.full((4, ROWS, COLS), 255), "uint8", None)
    meta = {
        "source_ids": [f"scene-{day}"],
        "bands": ["class", "confidence", "flags"],
        "units": ["class", "class", "bitmask"],
        "value_range": [[0, 3], [0, 2], [0, 15]],
        "code_version": "test",
    }
    publish("snow_obs", day, {"data": data, "display": display}, meta, storage)


class RunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.storage = LocalStorage(self.tmp / "catalogue")
        first = np.where(ELEVATION >= 1600.0, SNOW, NO_SNOW).astype("uint8")
        second = np.where(ELEVATION >= 2200.0, SNOW, NO_SNOW).astype("uint8")
        second[:5] = CLOUD
        first[:, :3] = NODATA  # outside the domain
        second[:, :3] = NODATA
        publish_observation(self.storage, self.tmp, "2026-03-02", first)
        publish_observation(self.storage, self.tmp, "2026-03-06", second)
        rebuild_index(self.storage)
        static = mock.patch.object(run, "load_static", return_value=(ELEVATION, np.zeros((ROWS, COLS), bool)))
        static.start()
        self.addCleanup(static.stop)

    def test_every_day_is_filled_published_and_flagged(self) -> None:
        import rasterio

        out = self.tmp / "out"
        summaries = run.run(self.storage, date(2026, 3, 2), date(2026, 3, 8), out, publish=True, version="test")
        self.assertEqual([s["date"] for s in summaries], [f"2026-03-0{d}" for d in range(2, 9)])
        flags = {s["date"]: s["flags"] for s in summaries}
        self.assertEqual(flags["2026-03-04"], [])
        self.assertEqual(flags["2026-03-06"], [])
        self.assertEqual(flags["2026-03-07"], ["extrapolated"])
        rebuild_index(self.storage)
        index = json.loads(self.storage.read("catalog/index.json").data)  # type: ignore[union-attr]
        entries = index["layers"]["snow_gapfill"]["entries"]
        self.assertEqual(len(entries), 7)
        self.assertEqual({e["status"] for e in entries}, {"gapfilled"})
        self.assertIn("extrapolated", entries[-1]["qa"]["flags"])
        self.assertEqual(entries[2]["source_ids"], sorted(e["cog"] for e in index["layers"]["snow_obs"]["entries"]))
        with rasterio.open(out / "2026-03-04" / "snow_gapfill.tif") as src:
            self.assertEqual([src.descriptions[i] for i in range(4)], run.BANDS)
            probability, snow, days_since, method = src.read()
            self.assertEqual(src.nodata, f.NODATA)
        self.assertTrue((probability[:, :3] == f.NODATA).all())
        self.assertEqual(float(probability[20, 10]), 0.0)  # 1150 m, bare on both dates
        self.assertEqual(float(snow[20, 100]), 1.0)  # 2500 m, snow on both dates
        self.assertEqual(float(method[20, 60]), f.SNOWLINE_BETWEEN)  # 1900 m, snow then bare
        self.assertEqual(float(days_since[20, 60]), 2.0)

    def test_republishing_a_day_reuses_its_files(self) -> None:
        day = date(2026, 3, 4)
        first = run.run(self.storage, day, day, self.tmp / "a", publish=True, version="test")[0]
        second = run.run(self.storage, day, day, self.tmp / "b", publish=True, version="test")[0]
        self.assertEqual(first["entry"], second["entry"])

    def test_no_observation_near_the_range_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            run.load_observations(self.storage, date(2027, 1, 1), date(2027, 1, 2))

    def test_a_day_before_the_first_observation_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "the first is 2026-03-02"):
            run.run(self.storage, date(2026, 3, 1), date(2026, 3, 3), self.tmp / "out")

    def test_display_follows_the_probability_ramp(self) -> None:
        rgba = run.display_rgba(np.array([[0.05, 0.2, 0.6, 0.95, f.NODATA]], "float32"))
        self.assertEqual(rgba[3].tolist(), [[0, 115, 204, 230, 0]])
        self.assertEqual(tuple(rgba[:3, 0, 3]), (0x3E, 0x48, 0x91))


if __name__ == "__main__":
    unittest.main()
