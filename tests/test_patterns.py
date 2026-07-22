"""Tests for cadence bucketing and the sightings log round-trip."""

from datetime import datetime
from zoneinfo import ZoneInfo

from amc_monitor.patterns import bucket_by_weekday_hour, summarize
from amc_monitor.sightings import load_sightings, new_sighting, record_sighting

ET = ZoneInfo("America/New_York")


def _epoch(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=ET).timestamp()


def test_bucket_by_weekday_hour_counts_in_eastern():
    # 2026-07-22 is a Wednesday. Two drops at 2am ET, one at 3am ET.
    epochs = [
        _epoch(2026, 7, 22, 2),
        _epoch(2026, 7, 22, 2, 30),
        _epoch(2026, 7, 22, 3),
    ]
    weekday, hour = bucket_by_weekday_hour(epochs, ET)
    assert weekday[2] == 3  # Wednesday (Mon=0)
    assert hour[2] == 2
    assert hour[3] == 1


def test_summarize_handles_empty():
    assert "No sightings logged yet" in summarize([])


def test_summarize_reports_peak_window():
    epochs = [_epoch(2026, 7, 22, 2) for _ in range(5)]
    out = summarize(epochs)
    assert "Wed" in out
    assert "02:00" in out


def test_sightings_log_roundtrip(tmp_path):
    path = str(tmp_path / "s.jsonl")
    s = new_sighting("134717191", "The Odyssey", "IMAX 70mm", "2026-07-25T02:00:00Z")
    record_sighting(path, s)
    record_sighting(path, s)
    rows = load_sightings(path)
    assert len(rows) == 2
    assert rows[0]["showtime_id"] == "134717191"
    assert rows[0]["format_label"] == "IMAX 70mm"
    assert isinstance(rows[0]["first_seen_epoch"], float)


def test_load_sightings_missing_file_is_empty():
    assert load_sightings("/nonexistent/path/nope.jsonl") == []
