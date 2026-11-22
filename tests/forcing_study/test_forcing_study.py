import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import numpy as np

from pipelines.forcing_study import era5_land, openmeteo, stations, study
from pipelines.snow_model.forcing import forcing_from_records


def record(lat: float, lon: float, start: date, days: int, missing: int = 0) -> dict:
    hours = days * 24
    times = [(datetime.combine(start, datetime.min.time()) + timedelta(hours=h)).isoformat()[:16] for h in range(hours)]
    temperature = [float(h % 24) for h in range(hours)]
    for index in range(missing):
        temperature[5 + index] = None
    return {
        "latitude": lat,
        "longitude": lon,
        "elevation": 1500.0,
        "hourly": {
            "time": times,
            "temperature_2m": temperature,
            "precipitation": [1.0] * hours,
            "shortwave_radiation": [100.0] * hours,
        },
    }


class OpenMeteoTest(unittest.TestCase):
    def test_call_weight_follows_fractional_rule(self):
        self.assertEqual(openmeteo.call_weight(1, 14, 3), 1)
        self.assertEqual(openmeteo.call_weight(10, 28, 3), 20)
        self.assertEqual(openmeteo.call_weight(2, 7, 20), 4)

    def test_missing_fraction_counts_raw_gaps(self):
        start = date(2024, 1, 1)
        records = [record(37.0, -3.4, start, 10, missing=12), record(37.1, -3.4, start, 10)]
        fractions = openmeteo.missing_fraction(records, start, date(2024, 1, 10))
        self.assertAlmostEqual(fractions["temperature_2m"], 12 / 480, places=6)
        self.assertEqual(fractions["precipitation"], 0)

    def test_gaps_over_two_percent_are_refused(self):
        start = date(2024, 1, 1)
        records = [record(37.0, -3.4, start, 10, missing=12)]
        with self.assertRaises(RuntimeError):
            forcing_from_records(records, start, date(2024, 1, 10))

    def test_cached_get_reads_cache_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            ledger = openmeteo.Ledger(cache / "ledger.jsonl")
            payload = {"latitude": 1}
            with mock.patch("urllib.request.urlopen") as opener:
                opener.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
                with mock.patch("json.load", return_value=payload):
                    first = openmeteo.cached_get("https://example.test/a", 1, cache, ledger)
                second = openmeteo.cached_get("https://example.test/a", 1, cache, ledger)
            self.assertEqual(opener.call_count, 1)
            self.assertEqual(first, second)
            self.assertEqual(len(ledger._entries()), 1)

    def test_ledger_waits_when_minute_budget_is_spent(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = openmeteo.Ledger(Path(folder) / "ledger.jsonl")
            ledger.spend(openmeteo.LIMITS[0][1])
            sleeps = []

            def fake_sleep(seconds):
                sleeps.append(seconds)
                ledger.path.write_text("", encoding="utf-8")

            with mock.patch("time.sleep", fake_sleep):
                ledger.wait_for(1)
            self.assertEqual(len(sleeps), 1)
            self.assertGreater(sleeps[0], 50)


class StationsTest(unittest.TestCase):
    def test_dms_parsing(self):
        self.assertAlmostEqual(stations.dms_to_degrees("365523000N"), 36 + 55 / 60 + 23 / 3600, places=6)
        self.assertAlmostEqual(stations.dms_to_degrees("031102000W"), -(3 + 11 / 60 + 2 / 3600), places=6)
        self.assertAlmostEqual(stations.dms_to_degrees("370600N"), 37.1, places=6)
        self.assertAlmostEqual(stations.dms_to_degrees("032412W"), -3.4033333, places=6)

    def test_aemet_values(self):
        self.assertEqual(stations.aemet_value("12,4"), 12.4)
        self.assertEqual(stations.aemet_value("Ip"), 0.0)
        self.assertIsNone(stations.aemet_value("Acum"))
        self.assertIsNone(stations.aemet_value(None))

    def test_near(self):
        station = stations.Station("RIA", "18-7", "Cadiar", 36.92, -3.18, 928)
        self.assertTrue(stations.near(station, (-3.64, 36.91, -2.59, 37.25), 0.3))
        self.assertFalse(stations.near(station, (-2.0, 36.91, -1.0, 37.25), 0.3))


class Era5LandTest(unittest.TestCase):
    def test_deaccumulate(self):
        # Accumulations since 00 UTC: 00 closes the previous day, 01 is the first hour.
        hours = np.array([23, 0, 1, 2, 3])
        values = np.array([[5.0, 6.0, 1.0, 3.0, 3.0]])
        amounts = era5_land.deaccumulate(values, hours)
        np.testing.assert_allclose(amounts[0, 1:], [1.0, 1.0, 2.0, 0.0])

    def test_grib_round_trip(self):
        import eccodes

        start = date(2024, 1, 1)
        with tempfile.TemporaryDirectory() as folder:
            data_path = Path(folder) / "data.grib"
            orography_path = Path(folder) / "z.grib"

            def write(handle, short_name, valid, values):
                message = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib1")
                for key, value in (
                    ("Ni", 2),
                    ("Nj", 2),
                    ("latitudeOfFirstGridPointInDegrees", 37.1),
                    ("longitudeOfFirstGridPointInDegrees", -3.4),
                    ("latitudeOfLastGridPointInDegrees", 37.0),
                    ("longitudeOfLastGridPointInDegrees", -3.3),
                    ("iDirectionIncrementInDegrees", 0.1),
                    ("jDirectionIncrementInDegrees", 0.1),
                    ("bitmapPresent", 1),
                    ("missingValue", 9999),
                ):
                    eccodes.codes_set(message, key, value)
                eccodes.codes_set(message, "shortName", short_name)
                eccodes.codes_set(message, "dataDate", int(valid.strftime("%Y%m%d")))
                eccodes.codes_set(message, "dataTime", valid.hour * 100)
                eccodes.codes_set_values(message, values)
                eccodes.codes_write(message, handle)
                eccodes.codes_release(message)

            origin = datetime(2024, 1, 1)
            with data_path.open("wb") as handle:
                for hour in range(25):
                    valid = origin + timedelta(hours=hour)
                    accumulated_hours = 24 if valid.hour == 0 else valid.hour
                    write(handle, "2t", valid, [273.15 + hour, 274.15, 275.15, 9999])
                    write(handle, "tp", valid, [0.001 * accumulated_hours] * 3 + [9999])
                    write(handle, "ssrd", valid, [3600.0 * 100 * accumulated_hours] * 3 + [9999])
            with orography_path.open("wb") as handle:
                write(handle, "z", origin, [9806.65, 19613.3, 29419.95, 9999])

            forcing = era5_land.forcing_from_grib([data_path], orography_path, start, start)
        self.assertEqual(forcing.temperature.shape, (3, 1, 24))
        np.testing.assert_allclose(forcing.elevation, [1000, 2000, 3000], rtol=1e-5)
        np.testing.assert_allclose(forcing.temperature[0, 0, :3], [0, 1, 2], atol=1e-4)
        np.testing.assert_allclose(forcing.precipitation[:, 0, :], 1.0, atol=1e-4)
        np.testing.assert_allclose(forcing.shortwave[:, 0], 100.0, rtol=1e-4)
        np.testing.assert_allclose(forcing.lat, [37.1, 37.1, 37.0])


class ScoringTest(unittest.TestCase):
    def test_confusion_and_false_snow_share(self):
        predicted = np.array([True, True, True, False, False])
        observed = np.array([True, False, True, True, False])
        result = study.confusion(predicted, observed)
        self.assertEqual((result["tp"], result["fp"], result["fn"], result["tn"]), (2, 1, 1, 1))
        self.assertAlmostEqual(result["false_snow_share"], 1 / 3, places=4)
        self.assertAlmostEqual(result["f1"], 2 / 3, places=4)

    def test_score_holds_out_every_third_date_and_prefers_the_right_member(self):
        cells = 8
        elevation = np.linspace(1000, 3400, cells).astype("float32")
        truth = elevation >= 2200
        usable = np.ones(cells, dtype=bool)
        good, bad = np.packbits(truth), np.packbits(~truth)
        references = [study.Reference(date(2024, 1, 1) + timedelta(days=i), truth, usable) for i in range(6)]
        masks = [[good, bad, bad] for _ in references]
        settings = {"ensemble": {"target_effective_members": 1}}
        result = study.score(masks, references, elevation, settings)
        self.assertEqual(result["test_dates"], ["2024-01-03", "2024-01-06"])
        self.assertEqual(result["weighted"]["all_dates"]["all"]["accuracy"], 1.0)
        self.assertEqual(result["prior"]["all_dates"]["all"]["accuracy"], 0.0)
        self.assertIn("2500-3000", result["weighted"]["all_dates"])

    def test_precipitation_metrics(self):
        days = [date(2024, 1, 1) + timedelta(days=i) for i in range(40)]
        station = {day: (5.0 if i % 4 == 0 else 0.0) for i, day in enumerate(days)}
        model = {day: 2 * value for day, value in station.items()}
        result = study.precipitation_metrics(model, station)
        self.assertEqual(result["ratio"], 2.0)
        self.assertEqual(result["daily_r"], 1.0)
        self.assertEqual(result["wet_day_pod"], 1.0)
        self.assertEqual(result["wet_day_far"], 0.0)
        self.assertIsNone(study.precipitation_metrics(dict(list(model.items())[:10]), station))

    def test_daily_totals_respect_day_start(self):
        origin = datetime(2024, 1, 1)
        times = [origin + timedelta(hours=h) for h in range(72)]
        values = np.zeros(72)
        values[30] = 4.0  # 06 UTC on 2 January, before a 07 UTC day boundary
        utc = study.daily_totals(times, values, 0)
        aemet = study.daily_totals(times, values, 7)
        self.assertEqual(utc[date(2024, 1, 2)], 4.0)
        self.assertEqual(aemet[date(2024, 1, 1)], 4.0)
        self.assertNotIn(date(2023, 12, 31), aemet)

    def test_season_bounds_cut_at_yesterday(self):
        self.assertEqual(study.season_bounds(2024, date(2026, 11, 22)), (date(2024, 10, 1), date(2025, 9, 30)))
        self.assertEqual(study.season_bounds(2026, date(2026, 11, 22)), (date(2026, 10, 1), date(2026, 11, 21)))


if __name__ == "__main__":
    unittest.main()
