import json
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

from pipelines.catalog import LocalStorage
from pipelines.snow_obs import backfill


def test_windows_cover_the_range_once_in_weeks():
    windows = backfill.windows(date(2022, 12, 20), date(2023, 1, 20))
    assert windows[0].start == date(2022, 12, 20) and windows[-1].end == date(2023, 1, 20)
    for before, after in zip(windows, windows[1:]):
        assert (after.start - before.end).days == 1
    assert all((w.end - w.start).days < backfill.WINDOW_DAYS for w in windows)
    assert [(w.end - w.start).days + 1 for w in windows[:-1]] == [backfill.WINDOW_DAYS] * (len(windows) - 1)


def test_windows_of_a_single_day():
    only = backfill.windows(date(2025, 2, 3), date(2025, 2, 3))
    assert [(w.start, w.end) for w in only] == [(date(2025, 2, 3), date(2025, 2, 3))]


def test_published_dates_read_the_catalogue_entries(tmp_path):
    storage = LocalStorage(tmp_path)
    for day in ("2025-01-02", "2025-01-07"):
        storage.write(f"catalog/entries/snow_obs/{day}.json", b"{}", "application/json", "no-cache")
    storage.write("catalog/entries/rgb/2025-01-03.json", b"{}", "application/json", "no-cache")
    assert backfill.published_dates(storage) == {date(2025, 1, 2), date(2025, 1, 7)}


def test_pending_range_skips_published_edges_only():
    window = backfill.Window(date(2025, 1, 1), date(2025, 1, 7))
    assert backfill.pending_range(window, {date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 7)}) == (
        date(2025, 1, 3),
        date(2025, 1, 6),
    )
    assert (
        backfill.pending_range(window, {date(2025, 1, 1) + (date(2025, 1, d) - date(2025, 1, 1)) for d in range(1, 8)})
        is None
    )


def test_a_rerun_skips_published_windows_and_retries_then_reports_a_failed_one(tmp_path):
    storage = LocalStorage(tmp_path / "bucket")
    storage.write("catalog/entries/snow_obs/2025-01-01.json", b"{}", "application/json", "no-cache")
    calls = []

    def fake_window(domain, window, first, last, work, static_cache, target):
        calls.append((first, last))
        if first == date(2025, 1, 8):
            raise OSError("tile read failed")
        return {first.isoformat(): {"found": True, "complete": True, "observed_fraction": 0.9, "in_catalogue": True}}

    with (
        mock.patch("pipelines.catalog.storage_from_env", return_value=storage),
        mock.patch.object(backfill, "run_window", fake_window),
        mock.patch.object(backfill, "RETRY_PAUSE_SECONDS", 0),
    ):
        rows, failed = backfill.run(Path("domain.geojson"), date(2025, 1, 1), date(2025, 1, 14), tmp_path, "staging")
    assert calls[0] == (date(2025, 1, 2), date(2025, 1, 7))
    assert calls.count((date(2025, 1, 8), date(2025, 1, 14))) == backfill.ATTEMPTS
    assert failed == ["2025-01-08..2025-01-14"]
    assert rows["2025-01-01"]["in_catalogue"] and rows["2025-01-02"]["in_catalogue"]


def test_main_exits_non_zero_when_a_window_failed(tmp_path):
    with mock.patch.object(backfill, "run", return_value=({}, ["2025-01-08..2025-01-14"])):
        code = backfill.main(
            [
                "--domain",
                "d.geojson",
                "--start",
                "2025-01-01",
                "--end",
                "2025-01-14",
                "--work",
                str(tmp_path),
                "--target",
                "staging",
            ]
        )
    assert code == 1
    assert json.loads((tmp_path / "backfill-summary.json").read_text())["failed"] == ["2025-01-08..2025-01-14"]


def test_end_before_start_is_rejected(tmp_path):
    with pytest.raises(SystemExit):
        backfill.main(
            [
                "--domain",
                "d",
                "--start",
                "2025-02-01",
                "--end",
                "2025-01-01",
                "--work",
                str(tmp_path),
                "--target",
                "staging",
            ]
        )
